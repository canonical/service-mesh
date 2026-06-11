# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for utils.py deduplication functions."""

from canonical_service_mesh.models import (
    BackendRef,
    GRPCMethodMatch,
    GRPCRouteMatch,
    HTTPPathMatch,
    HTTPRouteMatch,
)
from charmlibs.interfaces.istio_ingress_route import (
    BackendRef as LibBackendRef,
)
from charmlibs.interfaces.istio_ingress_route import (
    HTTPPathMatch as LibHTTPPathMatch,
)
from charmlibs.interfaces.istio_ingress_route import (
    HTTPRoute as LibHTTPRoute,
)
from charmlibs.interfaces.istio_ingress_route import (
    HTTPRouteMatch as LibHTTPRouteMatch,
)
from charmlibs.interfaces.istio_ingress_route import (
    IstioIngressRouteConfig,
    Listener,
    ProtocolType,
)

from utils import clear_conflicting_routes, deduplicate_grpc_routes, deduplicate_http_routes


def test_deduplicate_http_routes_no_conflicts():
    """Test HTTP route deduplication when no conflicts exist."""
    all_http_routes = [
        {
            "name": "route1",
            "listener_port": 80,
            "listener_protocol": "HTTP",
            "namespace": "model1",
            "source_app": "app1",
            "source_relation": "ingress",
            "matches": [HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/api"))],
            "backend_refs": [BackendRef(name="svc1", port=8080, namespace="model1")],
            "filters": [],
        },
        {
            "name": "route2",
            "listener_port": 80,
            "listener_protocol": "HTTP",
            "namespace": "model1",
            "source_app": "app1",
            "source_relation": "ingress",
            "matches": [HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/api"))],
            "backend_refs": [BackendRef(name="svc1", port=8080, namespace="model1")],
            "filters": [],
        },
        {
            "name": "route3",
            "listener_port": 80,
            "listener_protocol": "HTTP",
            "namespace": "model2",
            "source_app": "app2",
            "source_relation": "ingress",
            "matches": [HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/users"))],
            "backend_refs": [BackendRef(name="svc2", port=8080, namespace="model2")],
            "filters": [],
        },
    ]

    valid_routes, apps_to_clear = deduplicate_http_routes(all_http_routes)

    # No conflicts: same app can have duplicate paths, different apps have different paths
    assert len(apps_to_clear) == 0
    assert len(valid_routes) == 3


def test_deduplicate_http_routes_with_conflicts():
    """Test HTTP route deduplication when conflicts exist."""
    all_http_routes = [
        {
            "name": "route1",
            "listener_port": 80,
            "listener_protocol": "HTTP",
            "namespace": "model1",
            "source_app": "app1",
            "source_relation": "ingress",
            "matches": [HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/api"))],
            "backend_refs": [BackendRef(name="svc1", port=8080, namespace="model1")],
            "filters": [],
        },
        {
            "name": "route2",
            "listener_port": 80,
            "listener_protocol": "HTTP",
            "namespace": "model2",
            "source_app": "app2",
            "source_relation": "istio-ingress-route",
            "matches": [HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/api"))],
            "backend_refs": [BackendRef(name="svc2", port=8080, namespace="model2")],
            "filters": [],
        },
        {
            "name": "route3",
            "listener_port": 80,
            "listener_protocol": "HTTP",
            "namespace": "model3",
            "source_app": "app3",
            "source_relation": "ingress",
            "matches": [HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/users"))],
            "backend_refs": [BackendRef(name="svc3", port=8080, namespace="model3")],
            "filters": [],
        },
    ]

    valid_routes, apps_to_clear = deduplicate_http_routes(all_http_routes)

    # Conflict: app1 and app2 both want /api on HTTP:80
    assert len(apps_to_clear) > 0
    assert ("app1", "ingress") in apps_to_clear
    assert ("app2", "istio-ingress-route") in apps_to_clear
    assert ("app3", "ingress") not in apps_to_clear

    # Only route3 (/users) should remain
    assert len(valid_routes) == 1
    assert valid_routes[0]["matches"][0].path.value == "/users"


def test_deduplicate_grpc_routes_no_conflicts():
    """Test gRPC route deduplication when no conflicts exist."""
    all_grpc_routes = [
        {
            "name": "route1",
            "listener_port": 9090,
            "listener_protocol": "HTTP",
            "namespace": "model1",
            "source_app": "app1",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(method=GRPCMethodMatch(service="UserService", method="GetUser"))
            ],
            "backend_refs": [BackendRef(name="grpc-svc1", port=9000, namespace="model1")],
        },
        {
            "name": "route2",
            "listener_port": 9090,
            "listener_protocol": "HTTP",
            "namespace": "model2",
            "source_app": "app2",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(method=GRPCMethodMatch(service="OrderService", method="GetOrder"))
            ],
            "backend_refs": [BackendRef(name="grpc-svc2", port=9000, namespace="model2")],
        },
    ]

    valid_routes, apps_to_clear = deduplicate_grpc_routes(all_grpc_routes)

    # No conflicts: different services
    assert len(apps_to_clear) == 0
    assert len(valid_routes) == 2


def test_deduplicate_grpc_routes_with_conflicts():
    """Test gRPC route deduplication when conflicts exist."""
    all_grpc_routes = [
        {
            "name": "route1",
            "listener_port": 9090,
            "listener_protocol": "HTTP",
            "namespace": "model1",
            "source_app": "app1",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(method=GRPCMethodMatch(service="UserService", method="GetUser"))
            ],
            "backend_refs": [BackendRef(name="grpc-svc1", port=9000, namespace="model1")],
        },
        {
            "name": "route2",
            "listener_port": 9090,
            "listener_protocol": "HTTP",
            "namespace": "model2",
            "source_app": "app2",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(method=GRPCMethodMatch(service="UserService", method="GetUser"))
            ],
            "backend_refs": [BackendRef(name="grpc-svc2", port=9000, namespace="model2")],
        },
        {
            "name": "route3",
            "listener_port": 9090,
            "listener_protocol": "HTTP",
            "namespace": "model3",
            "source_app": "app3",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(method=GRPCMethodMatch(service="OrderService", method="GetOrder"))
            ],
            "backend_refs": [BackendRef(name="grpc-svc3", port=9000, namespace="model3")],
        },
    ]

    valid_routes, apps_to_clear = deduplicate_grpc_routes(all_grpc_routes)

    # Conflict: app1 and app2 both want /UserService/GetUser on HTTP:9090
    assert len(apps_to_clear) > 0
    assert ("app1", "istio-ingress-route") in apps_to_clear
    assert ("app2", "istio-ingress-route") in apps_to_clear
    assert ("app3", "istio-ingress-route") not in apps_to_clear

    # Only route3 (OrderService) should remain
    assert len(valid_routes) == 1
    assert valid_routes[0]["matches"][0].method.service == "OrderService"


def test_clear_conflicting_routes():
    """Test clearing conflicting routes from original data structures."""
    # Create sample data structures
    application_route_data = {
        ("app1", "ingress"): {
            "handler": None,
            "routes": [{"prefix": "/api", "service_name": "svc1", "port": 8080}],
        },
        ("app2", "ingress"): {
            "handler": None,
            "routes": [{"prefix": "/users", "service_name": "svc2", "port": 8080}],
        },
    }

    http_listener = Listener(port=8080, protocol=ProtocolType.HTTP)
    istio_ingress_route_configs = {
        ("app3", "istio-ingress-route"): {
            "handler": None,
            "config": IstioIngressRouteConfig(
                model="model3",
                listeners=[http_listener],
                http_routes=[
                    LibHTTPRoute(
                        name="conflicting-route",
                        listener=http_listener,
                        backends=[LibBackendRef(service="svc3", port=80)],
                        matches=[
                            LibHTTPRouteMatch(
                                path=LibHTTPPathMatch(type="PathPrefix", value="/api")
                            )
                        ],
                    )
                ],
                grpc_routes=[],
            ),
        },
        ("app4", "istio-ingress-route"): {
            "handler": None,
            "config": IstioIngressRouteConfig(
                model="model4",
                listeners=[http_listener],
                http_routes=[
                    LibHTTPRoute(
                        name="ok-route",
                        listener=http_listener,
                        backends=[LibBackendRef(service="svc4", port=80)],
                        matches=[
                            LibHTTPRouteMatch(
                                path=LibHTTPPathMatch(type="PathPrefix", value="/admin")
                            )
                        ],
                    )
                ],
                grpc_routes=[],
            ),
        },
    }

    # Apps to clear due to conflicts
    apps_to_clear = {("app1", "ingress"), ("app3", "istio-ingress-route")}

    # Clear the conflicting routes
    clear_conflicting_routes(application_route_data, istio_ingress_route_configs, apps_to_clear)

    # Verify clearing
    assert len(application_route_data[("app1", "ingress")]["routes"]) == 0
    assert len(application_route_data[("app2", "ingress")]["routes"]) == 1

    assert len(istio_ingress_route_configs[("app3", "istio-ingress-route")]["config"].http_routes) == 0
    assert len(istio_ingress_route_configs[("app4", "istio-ingress-route")]["config"].http_routes) == 1
