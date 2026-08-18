#!/usr/bin/env python3
"""Charm for the Details microservice."""

import logging
from typing import Dict

from charms.istio_beacon_k8s.v0.service_mesh import (
    AppPolicy,
    Endpoint,
    Method,
    ServiceMeshConsumer,
    UnitPolicy,
)
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import LayerDict

from bookinfo_service import BookinfoServiceProvider

logger = logging.getLogger(__name__)

PORT = 9080


class DetailsK8sCharm(CharmBase):
    """Charm for the Details microservice."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(pebble_ready=False)

        self.container = self.unit.get_container("bookinfo-details")
        self.framework.observe(self.on.bookinfo_details_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.service_provider = BookinfoServiceProvider(
            charm=self,
            relation_name="details",
            port=PORT,
        )
        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                AppPolicy(
                    relation="details",
                    endpoints=[
                        Endpoint(
                            ports=[PORT], methods=[Method.get], paths=["/health", "/details/*"]
                        )
                    ],
                ),
                UnitPolicy(
                    relation="peers",
                    ports=[PORT],
                ),
            ],
        )
        self._set_ports()

    def _on_pebble_ready(self, event):
        """Handle the pebble ready event."""
        self._stored.pebble_ready = True
        self._reconcile()

    def _on_config_changed(self, event):
        """Handle config changed event."""
        self._reconcile()

    def _on_update_status(self, event):
        """Handle update status event."""
        self._reconcile()

    def _reconcile(self):
        """Reconcile the charm state.

        This is the main reconciliation loop that ensures the charm
        converges to the desired state regardless of which event triggered it.
        """
        if not self._stored.pebble_ready:
            self.unit.status = WaitingStatus("Waiting for pebble ready")
            return

        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for container")
            return

        try:
            self._update_layer()
            self._set_ports()

            # Check if service is running
            service = self.container.get_service("details")
            if service.is_running():
                self.unit.status = ActiveStatus("Ready")
            else:
                self.unit.status = MaintenanceStatus("Service not running")
        except Exception as e:
            logger.error(f"Failed to reconcile: {e}")
            self.unit.status = BlockedStatus(f"Failed to reconcile: {str(e)}")

    def _update_layer(self):
        """Update the Pebble layer configuration."""
        if not self.container.can_connect():
            logger.debug("Cannot connect to container")
            return

        layer = self._generate_layer()
        self.container.add_layer("details", layer, combine=True)

        try:
            self.container.replan()
            logger.info("Service layer updated")
        except Exception as e:
            logger.error(f"Failed to replan service: {e}")
            raise

    def _generate_layer(self) -> LayerDict:
        """Generate the Pebble layer configuration."""
        return {
            "summary": "Details service layer",
            "description": "Pebble layer for the Details microservice",
            "services": {
                "details": {
                    "override": "replace",
                    "summary": "Details service",
                    "command": f"ruby /opt/microservices/details.rb {PORT}",
                    "startup": "enabled",
                    "environment": self._get_environment(),
                }
            },
        }

    def _get_environment(self) -> Dict[str, str]:
        """Get environment variables for the service."""
        env = {
            "SERVICE_NAME": "details",
            "SERVICE_VERSION": "v1",
            # Experimental: log level may not actually affect the service logging
            "LOG_LEVEL": self.config["log-level"],
        }
        return env

    def _set_ports(self):
        """Open the application ports to fix Juju's 65535 placeholder issue."""
        try:
            self.unit.open_port("tcp", PORT)
            logger.info(f"Opened TCP port {PORT}")
        except Exception as e:
            logger.warning(f"Failed to open port: {e}")


if __name__ == "__main__":
    main(DetailsK8sCharm)
