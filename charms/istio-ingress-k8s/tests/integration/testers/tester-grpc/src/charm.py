#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from charmlibs.interfaces.istio_ingress_route import (
    BackendRef,
    GRPCMethodMatch,
    GRPCRoute,
    GRPCRouteMatch,
    IstioIngressRouteConfig,
    IstioIngressRouteRequirer,
    Listener,
    ProtocolType,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer


class GRPCTesterCharm(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.unit.set_ports(9000)

        # istio-ingress-route interface support
        self.istio_ingress_route = IstioIngressRouteRequirer(
            self, relation_name="istio-ingress-route"
        )

        self.framework.observe(self.on.grpc_server_pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.istio_ingress_route.on.ready, self._on_istio_ingress_route_ready
        )

    def _on_pebble_ready(self, _):
        container = self.unit.get_container("grpc-server")
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        layer = Layer(
            {
                "summary": "gRPC server layer",
                "description": "pebble config layer for gRPC server",
                "services": {
                    "grpc-server": {
                        "override": "replace",
                        "command": "/bin/grpcbin",
                        "startup": "enabled",
                    }
                },
            }
        )

        container.add_layer("grpc-server", layer, combine=True)
        container.autostart()
        self.unit.status = ActiveStatus("gRPC server running")

        # Configure istio-ingress-route if relation exists
        if self.model.get_relation("istio-ingress-route"):
            self._configure_istio_ingress_route()

    def _on_istio_ingress_route_ready(self, _):
        """Handle istio-ingress-route relation ready."""
        self._configure_istio_ingress_route()

    def _configure_istio_ingress_route(self):
        """Configure gRPC routes via istio-ingress-route."""
        # Define listener on port 9000 (grpcbin default)
        grpc_listener = Listener(port=9000, protocol=ProtocolType.GRPC)

        # Configure multiple gRPC routes for testing
        config = IstioIngressRouteConfig(
            model=self.model.name,
            listeners=[grpc_listener],
            grpc_routes=[
                # Route 1: grpcbin.GRPCBin/Empty method. predefined in the image.
                GRPCRoute(
                    name="empty-route",
                    listener=grpc_listener,
                    matches=[
                        GRPCRouteMatch(
                            method=GRPCMethodMatch(service="grpcbin.GRPCBin", method="Empty")
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=9000)],
                ),
                # Route 2: grpcbin.GRPCBin/HeadersUnary method. predefined in the image.
                GRPCRoute(
                    name="headersunary-route",
                    listener=grpc_listener,
                    matches=[
                        GRPCRouteMatch(
                            method=GRPCMethodMatch(service="grpcbin.GRPCBin", method="HeadersUnary")
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=9000)],
                ),
                # Route 3: gRPC reflection service for dynamic service discovery
                GRPCRoute(
                    name="reflection-route",
                    listener=grpc_listener,
                    matches=[
                        GRPCRouteMatch(
                            method=GRPCMethodMatch(
                                service="grpc.reflection.v1alpha.ServerReflection",
                                method="ServerReflectionInfo"
                            )
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=9000)],
                ),
            ],
        )
        self.istio_ingress_route.submit_config(config)


if __name__ == "__main__":
    main(GRPCTesterCharm)
