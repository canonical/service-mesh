#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops

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

    def _collect_state(self) -> CharmState:
        """Collect the charm's inputs into a validated state snapshot."""
        return CharmState(
            backend=str(self.config["backend"]),
            root_credential=(self.config.get("root-credential") or None),
            login_server=(str(self.config.get("login-server") or "") or None),
        )

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


if __name__ == "__main__":  # pragma: nocover
    ops.main(TailscaleConfigCharm)
