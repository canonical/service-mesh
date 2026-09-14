# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Host operations for the Tailscale snap and client."""

import fcntl
import hashlib
import json
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode

from charmlibs import snap

from credentials import ResolvedCredentials

SNAP_NAME = "tailscale"
CONFIGURATION_VERSION = "2"
STATE_DIRECTORY = Path("/var/lib/tailscale-beacon")
UNITS_DIRECTORY = STATE_DIRECTORY / "units"
CONNECTED_MARKER = STATE_DIRECTORY / "connected"
CONFIGURATION_MARKER = STATE_DIRECTORY / "configuration"
LOCK_FILE = STATE_DIRECTORY / "lifecycle.lock"


@dataclass(frozen=True)
class TailscaleStatus:
    """Relevant fields returned by ``tailscale status --json``."""

    backend_state: str
    dns_name: str = ""
    tailnet_name: str = ""


class Tailscale:
    """Manage one machine's shared Tailscale installation."""

    def __init__(self, unit_name: str):
        self._marker = UNITS_DIRECTORY / unit_name.replace("/", "-")

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Serialize all machine-wide lifecycle operations."""
        STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        with LOCK_FILE.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            yield

    def register_unit(self) -> None:
        """Register this subordinate as a user of the shared daemon."""
        UNITS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        self._marker.touch(exist_ok=True)

    def unregister_unit(self) -> None:
        """Unregister this subordinate as a user of the shared daemon."""
        if not self._marker.exists():
            return
        self._marker.unlink()

    @property
    def has_other_units(self) -> bool:
        """Return whether another subordinate currently uses the shared daemon."""
        if not UNITS_DIRECTORY.exists():
            return False
        return any(path != self._marker for path in UNITS_DIRECTORY.iterdir())

    def ensure_snap(self, channel: str) -> None:
        """Install the snap, or ensure an existing install tracks the channel."""
        snap.SnapCache()[SNAP_NAME].ensure(
            snap.SnapState.Present,
            channel=channel,
        )

    @property
    def snap_installed(self) -> bool:
        """Return whether the Tailscale snap is installed."""
        return snap.SnapCache()[SNAP_NAME].present

    def up(self, credentials: ResolvedCredentials) -> None:
        """Join or update the machine without persisting the supplied auth key."""
        command = [
            "/snap/bin/tailscale",
            "up",
            "--auth-key=file:/dev/stdin",
            f"--login-server={credentials.login_server}",
            "--reset",
        ]
        if credentials.auth_key.startswith("tskey-client-"):
            command.append("--force-reauth")
        if credentials.tags:
            command.append(f"--advertise-tags={','.join(credentials.tags)}")
        self._run(
            command,
            input_text=self._oauth_key_with_ephemeral_setting(
                credentials.auth_key, credentials.ephemeral
            ),
        )
        STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        CONNECTED_MARKER.touch(exist_ok=True)

    def configuration_is_current(
        self, credentials: ResolvedCredentials, channel: str
    ) -> bool:
        """Return whether this exact configuration is already applied."""
        if not self.snap_installed or not CONNECTED_MARKER.exists():
            return False
        return CONFIGURATION_MARKER.exists() and CONFIGURATION_MARKER.read_text() == (
            self._configuration_digest(credentials, channel)
        )

    def mark_configuration_current(
        self, credentials: ResolvedCredentials, channel: str
    ) -> None:
        """Record the applied configuration without storing credential material."""
        CONFIGURATION_MARKER.write_text(self._configuration_digest(credentials, channel))

    def disconnect(self) -> None:
        """Disconnect a session established by this charm."""
        if not CONNECTED_MARKER.exists():
            return
        if self.snap_installed:
            self._run(["/snap/bin/tailscale", "down"])
        CONNECTED_MARKER.unlink(missing_ok=True)
        CONFIGURATION_MARKER.unlink(missing_ok=True)

    def remove_snap(self) -> None:
        """Remove the snap if it is installed."""
        snap.remove(SNAP_NAME)

    def status(self) -> TailscaleStatus:
        """Read the local daemon status."""
        result = self._run(["/snap/bin/tailscale", "status", "--json"])
        payload: dict[str, Any] = json.loads(result.stdout)
        self_data = payload.get("Self") or {}
        tailnet_data = payload.get("CurrentTailnet") or {}
        return TailscaleStatus(
            backend_state=str(payload.get("BackendState", "")),
            dns_name=str(self_data.get("DNSName", "")).rstrip("."),
            tailnet_name=str(tailnet_data.get("Name", "")),
        )

    @staticmethod
    def _configuration_digest(
        credentials: ResolvedCredentials, channel: str
    ) -> str:
        payload = "\0".join(
            (
                credentials.auth_key,
                credentials.login_server,
                *credentials.tags,
                str(credentials.ephemeral),
                channel,
                CONFIGURATION_VERSION,
            )
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _oauth_key_with_ephemeral_setting(auth_key: str, ephemeral: bool) -> str:
        if not auth_key.startswith("tskey-client-"):
            return auth_key

        secret, _, query = auth_key.partition("?")
        parameters = [
            (name, value)
            for name, value in parse_qsl(query, keep_blank_values=True)
            if name != "ephemeral"
        ]
        parameters.append(("ephemeral", str(ephemeral).lower()))
        return f"{secret}?{urlencode(parameters)}"

    @staticmethod
    def _run(
        command: list[str], input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            check=True,
            text=True,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
