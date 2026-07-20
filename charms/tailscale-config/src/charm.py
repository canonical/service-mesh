#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops

from backend_tailscale import RootClientError, get_root_client_info
from tailscale_config import CharmState, get_charm_status

logger = logging.getLogger(__name__)


class TailscaleConfigCharm(ops.CharmBase):
    """Charm the application.

    tailscale-config is a workloadless charm: it runs no Pebble services and
    manages no workload container. Its behavior is entirely credential
    minting/distribution.

    It follows a reconciler pattern: every observed hook runs the idempotent
    ``_reconcile`` method, which first collects the charm state and then
    performs the steps needed to converge on that state.
    """

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.config_changed, self._reconcile)
        framework.observe(self.on.start, self._reconcile)
        framework.observe(self.on.update_status, self._reconcile)
        framework.observe(self.on.secret_changed, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on.get_root_client_info_action, self._on_get_root_client_info)

    def _collect_state(self) -> CharmState:
        """Collect the charm's inputs into a validated state snapshot."""
        root_credential = str(self.config.get("root-credential") or "") or None
        return CharmState(
            backend=str(self.config["backend"]),
            root_credential=root_credential,
            root_credential_content=self._resolve_secret(root_credential),
            login_server=(str(self.config.get("login-server") or "") or None),
        )

    def _resolve_secret(self, uri: str | None) -> dict[str, str] | None:
        """Resolve a Juju secret URI to its content, or ``None`` if unavailable."""
        if uri is None:
            return None
        try:
            return self.model.get_secret(id=uri).get_content(refresh=True)
        except ops.SecretNotFoundError:
            logger.debug("secret %r not found or not granted to this application", uri)
            return None

    def _reconcile(self, _: ops.EventBase) -> None:
        """Idempotently converge the charm on its collected state.

        Runs on every observed hook. Credential minting/distribution against
        the control-plane API will be driven from here once implemented.
        """
        state = self._collect_state()
        if not state.has_valid_backend():
            logger.debug("invalid backend %r; skipping reconcile work", state.backend)
            return
        if state.root_credential is None:
            logger.debug("root credential not set; skipping reconcile work")
            return
        # TODO: mint and distribute per-relation credentials from here.

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the unit status."""
        event.add_status(get_charm_status(self._collect_state()))

    def _on_get_root_client_info(self, event: ops.ActionEvent) -> None:
        """Print information about the root OAuth client."""
        try:
            info = get_root_client_info(self._collect_state())
        except RootClientError as exc:
            logger.warning("failed to fetch root OAuth client info: %s", exc)
            event.fail(str(exc))
            return

        event.set_results(
            {
                "id": info.id,
                "key-type": info.key_type or "",
                "created": info.created or "",
                "scopes": ", ".join(info.scopes),
                "user-id": info.user_id or "",
            }
        )


if __name__ == "__main__":  # pragma: nocover
    ops.main(TailscaleConfigCharm)
