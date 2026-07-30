#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Test-only requirer charm for the tailscale_credentials interface.

This charm exists solely to exercise the tailscale-config provider end to end.
It reads the credential minted and distributed over the tailscale_credentials
relation, then proves the credential is usable by exchanging it for a
short-lived Tailscale access token. It reaches ActiveStatus only if that
exchange succeeds.

Verification runs at most once: the success is persisted in ``StoredState`` so
the charm makes no further API calls (and mints no further tokens) on
subsequent hooks.

The charm deliberately duplicates a tiny amount of the OAuth token-exchange
logic (it cannot import the tailscale-config charm's ``src/``), keeping it to
a single minimal API call.
"""

import http.client
import logging
import urllib.parse

import ops
from canonical_service_mesh.interfaces.tailscale_credentials import (
    TailscaleCredentials,
    TailscaleCredentialsRequirer,
)

logger = logging.getLogger(__name__)

RELATION_NAME = "tailscale-credentials"
TAILSCALE_API_HOST = "api.tailscale.com"
_TOKEN_PATH = "/api/v2/oauth/token"


class CredentialVerificationError(Exception):
    """Raised when the received credential cannot be verified against the API."""


class DummyRequirerCharm(ops.CharmBase):
    """Minimal requirer that verifies the minted credential works.

    Verification is performed at most once. To avoid consuming Tailscale API
    tokens on every hook, the successful result is persisted with
    ``ops.StoredState``; once verified, the charm stays active without any
    further API calls.
    """

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._stored.set_default(verified=False)
        self.credentials = TailscaleCredentialsRequirer(self.model.relations, self.app)
        framework.observe(self.on[RELATION_NAME].relation_changed, self._on_event)
        framework.observe(self.on[RELATION_NAME].relation_broken, self._on_event)
        framework.observe(self.on.secret_changed, self._on_event)
        framework.observe(self.on.update_status, self._on_event)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _on_event(self, _: ops.EventBase) -> None:
        """Verify the credential once, persisting success.

        Runs the (single) API-backed verification only while not yet verified.
        Status itself is reported by the collect-unit-status handler; this
        handler owns the one-shot verification and its persistence.
        """
        if self._stored.verified:
            return
        credentials = self._read_credential()
        if credentials is None:
            return
        try:
            _verify_credential(credentials.client_id, credentials.auth_key)
        except Exception:  # noqa: BLE001 - reported via collect-unit-status
            logger.exception("credential verification failed")
            return
        self._stored.verified = True
        logger.info("credential verified; no further API calls will be made")

    def _read_credential(self) -> "TailscaleCredentials | None":
        """Return the received credential, or ``None`` if not yet available."""
        relations = self.credentials.relations
        if not relations:
            return None
        provider_data = self.credentials.get_provider_data(relations[0])
        if provider_data is None or not provider_data.is_ready_for_use():
            return None
        assert provider_data.secret_id is not None  # guaranteed by is_ready_for_use
        try:
            content = self.model.get_secret(id=provider_data.secret_id).get_content(refresh=True)
        except ops.SecretNotFoundError:
            return None
        try:
            return TailscaleCredentials.model_validate(content)
        except Exception:  # noqa: BLE001 - reported via collect-unit-status
            logger.exception("received credential is invalid")
            return None

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report status based on the persisted verification result."""
        if self._stored.verified:
            event.add_status(ops.ActiveStatus("credential verified"))
            return
        if not self.credentials.relations:
            event.add_status(ops.WaitingStatus("waiting for tailscale-credentials relation"))
            return
        event.add_status(ops.WaitingStatus("waiting to verify credential"))


def _verify_credential(client_id: str, client_secret: str) -> None:
    """Exchange the credential for a short-lived access token.

    Performs a single OAuth2 ``client_credentials`` grant against the Tailscale
    token endpoint. Raises ``CredentialVerificationError`` if the exchange fails
    or returns no access token.
    """
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    conn = http.client.HTTPSConnection(TAILSCALE_API_HOST)
    try:
        conn.request(
            "POST",
            _TOKEN_PATH,
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        status = response.status
    except OSError as exc:
        raise CredentialVerificationError(f"failed to reach {TAILSCALE_API_HOST}: {exc}") from exc
    finally:
        conn.close()

    if not 200 <= status < 300:
        raise CredentialVerificationError(f"token endpoint returned HTTP {status}")
    if '"access_token"' not in payload:
        raise CredentialVerificationError("token endpoint response contained no access_token")


if __name__ == "__main__":  # pragma: nocover
    ops.main(DummyRequirerCharm)
