#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from charmlibs.interfaces.gateway_metadata import GatewayMetadataRequirer
from charmlibs.interfaces.istio_ingress_route import (
    BackendRef,
    HTTPPathMatch,
    HTTPPathMatchType,
    HTTPRoute,
    HTTPRouteMatch,
    IstioIngressRouteConfig,
    IstioIngressRouteRequirer,
    Listener,
    PathModifier,
    PathModifierType,
    ProtocolType,
    URLRewriteFilter,
    URLRewriteSpec,
)
from charmlibs.interfaces.istio_request_auth import (
    IstioRequestAuthRequirer,
    JWTRule,
)
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer


class HTTPTesterCharm(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.unit.set_ports(8080)

        # IPA interface support
        self.ipa = IngressPerAppRequirer(self, port=8080, relation_name="ingress")
        # Useful for manual testing of duplicated ingresses
        self.ipa2 = IngressPerAppRequirer(self, port=8080, relation_name="ingress-2")

        # istio-ingress-route interface support
        self.istio_ingress_route = IstioIngressRouteRequirer(
            self, relation_name="istio-ingress-route"
        )

        # gateway-metadata interface support
        self.gateway_metadata = GatewayMetadataRequirer(
            self, relation_name="gateway-metadata"
        )

        # istio-request-auth interface support
        self.request_auth = IstioRequestAuthRequirer(self, relation_name="istio-request-auth")

        self.framework.observe(self.on.echo_server_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.set_request_auth_action, self._on_set_request_auth)
        self.framework.observe(self.on.clear_request_auth_action, self._on_clear_request_auth)
        self.framework.observe(
            self.istio_ingress_route.on.ready, self._on_istio_ingress_route_ready
        )

    def _on_pebble_ready(self, _):
        container = self.unit.get_container("echo-server")
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        layer = Layer(
            {
                "summary": "echo server layer",
                "description": "pebble config layer for echo server",
                "services": {
                    "echo-server": {
                        "override": "replace",
                        "command": "/bin/echo-server",
                        "startup": "enabled",
                    }
                },
            }
        )

        container.add_layer("echo-server", layer, combine=True)
        container.autostart()
        self.unit.status = ActiveStatus("Echo server running")

        # Configure istio-ingress-route if relation exists
        if self.model.get_relation("istio-ingress-route"):
            self._configure_istio_ingress_route()

    def _on_istio_ingress_route_ready(self, _):
        """Handle istio-ingress-route relation ready."""
        self._configure_istio_ingress_route()

    def _configure_istio_ingress_route(self):
        """Configure HTTP routes via istio-ingress-route."""
        # Define listener on custom port 8080
        http_listener = Listener(port=8080, protocol=ProtocolType.HTTP)
        # Second listener on port 9090 to test multi-port auth policy aggregation.
        # The tester does not serve on this port; we only need to verify that
        # the ingress charm creates a single AuthorizationPolicy with both ports.
        extra_listener = Listener(port=9090, protocol=ProtocolType.HTTP)

        # Configure multiple HTTP routes for testing
        config = IstioIngressRouteConfig(
            model=self.model.name,
            listeners=[http_listener, extra_listener],
            http_routes=[
                # Route 1: /api path
                HTTPRoute(
                    name="api-route",
                    listener=http_listener,
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type=HTTPPathMatchType.PathPrefix, value="/api")
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=8080)],
                ),
                # Route 2: /health path
                HTTPRoute(
                    name="health-route",
                    listener=http_listener,
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type=HTTPPathMatchType.PathPrefix, value="/health")
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=8080)],
                ),
                # Route 3: /old-api path with URLRewrite filter
                HTTPRoute(
                    name="rewrite-route",
                    listener=http_listener,
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type=HTTPPathMatchType.PathPrefix, value="/old-api")
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=8080)],
                    filters=[
                        URLRewriteFilter(
                            urlRewrite=URLRewriteSpec(
                                path=PathModifier(
                                    type=PathModifierType.ReplacePrefixMatch,
                                    value="/api"
                                )
                            )
                        )
                    ],
                ),
                # Route 4: /extra path on port 9090 — tests multi-port policy aggregation
                HTTPRoute(
                    name="extra-port-route",
                    listener=extra_listener,
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type=HTTPPathMatchType.PathPrefix, value="/extra")
                        )
                    ],
                    backends=[BackendRef(service=self.app.name, port=9090)],
                ),
            ],
        )
        self.istio_ingress_route.submit_config(config)

    def _on_set_request_auth(self, event):
        """Publish JWT rules to the request-auth relation."""
        jwt_rule = JWTRule(
            issuer=event.params["issuer"],
            jwks_uri=event.params.get("jwks-uri"),
            forward_original_token=event.params.get("forward-original-token", True),
        )
        self.request_auth.publish_data([jwt_rule])
        event.set_results({"result": "ok"})

    def _on_clear_request_auth(self, event):
        """Clear JWT rules from the request-auth relation databag."""
        for relation in self.model.relations.get("istio-request-auth", []):
            relation.data[self.app].clear()
        event.set_results({"result": "ok"})


if __name__ == "__main__":
    main(HTTPTesterCharm)
