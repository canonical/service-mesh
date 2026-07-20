#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops

logger = logging.getLogger(__name__)


class TailscaleConfigCharm(ops.CharmBase):
    """Charm the application.

    tailscale-config is a workloadless charm: it runs no Pebble services and
    manages no workload container. Its behavior is entirely credential
    minting/distribution.
    """

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the unit status."""
        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":  # pragma: nocover
    ops.main(TailscaleConfigCharm)
