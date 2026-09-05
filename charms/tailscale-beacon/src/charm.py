#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A subordinate machine charm that joins its host to a tailnet."""

import json
import logging
import subprocess

import ops

from credentials import resolve_credentials
from tailscale import Tailscale

LOGGER = logging.getLogger(__name__)


class TailscaleBeaconCharm(ops.CharmBase):
    """Install and reconcile the shared Tailscale daemon on a Juju machine."""

    def __init__(self, *args):
        super().__init__(*args)
        self.tailscale = Tailscale(self.unit.name)

        for event in (
            self.on.install,
            self.on.start,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on.secret_changed,
        ):
            self.framework.observe(event, self._reconcile)
        for event in (
            self.on["tailscale-credentials"].relation_created,
            self.on["tailscale-credentials"].relation_changed,
            self.on["tailscale-credentials"].relation_broken,
        ):
            self.framework.observe(event, self._reconcile)
        self.framework.observe(self.on.stop, self._teardown)
        self.framework.observe(self.on.remove, self._teardown)
        self.framework.observe(self.on.collect_unit_status, self._collect_status)

    def _reconcile(self, _event: ops.EventBase) -> None:
        """Converge the machine onto the requested snap and tailnet state."""
        with self.tailscale.lock():
            self.tailscale.register_unit()
            credentials, error = resolve_credentials(self)
            if credentials is None:
                assert error is not None
                self.tailscale.disconnect()
                self.unit.status = self._credential_error_status(error)
                return

            channel = str(self.config["snap-channel"])
            if self.tailscale.configuration_is_current(credentials, channel):
                self.unit.status = self._runtime_status()
                return

            self.unit.status = ops.MaintenanceStatus("Installing Tailscale snap")
            self.tailscale.ensure_snap(channel)
            self.unit.status = ops.MaintenanceStatus("Connecting to tailnet")
            self.tailscale.up(credentials)
            self.tailscale.mark_configuration_current(credentials, channel)
            self.unit.status = self._runtime_status()

    def _collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report credential and daemon readiness without changing host state."""
        credentials, error = resolve_credentials(self)
        if credentials is None:
            assert error is not None
            event.add_status(self._credential_error_status(error))
            return
        if not self.tailscale.snap_installed:
            event.add_status(ops.BlockedStatus("Tailscale snap is not installed"))
            return
        event.add_status(self._runtime_status())

    def _runtime_status(self) -> ops.StatusBase:
        try:
            status = self.tailscale.status()
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            LOGGER.error("Failed to read Tailscale status: %s", error)
            return ops.BlockedStatus("Cannot read Tailscale status")

        if status.backend_state == "Running":
            identity = status.dns_name or status.tailnet_name
            message = f"Connected as {identity}" if identity else "Connected to tailnet"
            return ops.ActiveStatus(message)
        if status.backend_state == "NeedsMachineAuth":
            return ops.BlockedStatus("Tailnet device requires administrator approval")
        if status.backend_state in {"Starting", "NeedsLogin"}:
            return ops.WaitingStatus(f"Tailscale is {status.backend_state}")
        return ops.BlockedStatus(
            f"Tailscale backend is {status.backend_state or 'unavailable'}"
        )

    def _teardown(self, _event: ops.EventBase) -> None:
        """Disconnect only after the final subordinate leaves this machine."""
        with self.tailscale.lock():
            if self.tailscale.has_other_units:
                self.tailscale.unregister_unit()
                return
            self.tailscale.disconnect()
            if bool(self.config["remove-snap"]):
                self.tailscale.remove_snap()
            self.tailscale.unregister_unit()

    @staticmethod
    def _credential_error_status(error: str) -> ops.StatusBase:
        if error.startswith("Waiting for") or "not yet available" in error:
            return ops.WaitingStatus(error)
        return ops.BlockedStatus(error)


if __name__ == "__main__":
    ops.main(TailscaleBeaconCharm)
