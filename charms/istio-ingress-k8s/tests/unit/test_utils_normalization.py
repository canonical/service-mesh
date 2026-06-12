# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for utils.py normalization functions."""

from charmlibs.interfaces.istio_ingress_route import (
    BackendRef as LibBackendRef,
)
from charmlibs.interfaces.istio_ingress_route import (
    FilterType,
    GRPCMethodMatch,
    IstioIngressRouteConfig,
    Listener,
    ProtocolType,
)
from charmlibs.interfaces.istio_ingress_route import (
    GRPCRoute as LibGRPCRoute,
)
from charmlibs.interfaces.istio_ingress_route import (
    GRPCRouteMatch as LibGRPCRouteMatch,
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

from utils import (
    deduplicate_listeners,
    get_unauthenticated_paths,
    get_unauthenticated_paths_from_istio_ingress_route_configs,
    normalize_ipa_listeners,
    normalize_ipa_routes,
    normalize_istio_ingress_route_grpc_routes,
    normalize_istio_ingress_route_http_routes,
    normalize_istio_ingress_route_listeners,
)


def test_normalize_ipa_listeners_without_tls():
    """Test normalizing IPA listeners without TLS creates single HTTP listener."""
    tls_secret_name = None

    listeners = normalize_ipa_listeners(tls_secret_name)

    assert len(listeners) == 1
    assert listeners[0]["port"] == 80
    assert listeners[0]["gateway_protocol"] == "HTTP"
    assert listeners[0]["tls_secret_name"] is None
    assert listeners[0]["source_app"] == "ipa"


def test_normalize_ipa_listeners_with_tls():
    """Test normalizing IPA listeners with TLS creates HTTP and HTTPS listeners."""
    tls_secret_name = "my-tls-secret"

    listeners = normalize_ipa_listeners(tls_secret_name)

    assert len(listeners) == 2
    http_listener = [listener for listener in listeners if listener["port"] == 80][0]
    https_listener = [listener for listener in listeners if listener["port"] == 443][0]

    assert http_listener["gateway_protocol"] == "HTTP"
    assert http_listener["tls_secret_name"] is None

    assert https_listener["gateway_protocol"] == "HTTPS"
    assert https_listener["tls_secret_name"] == "my-tls-secret"


def test_normalize_istio_ingress_route_listeners_without_tls():
    """Test normalizing istio-ingress-route listeners without TLS for HTTP and gRPC."""
    http_listener = Listener(port=8080, protocol=ProtocolType.HTTP)
    grpc_listener = Listener(port=9090, protocol=ProtocolType.GRPC)

    istio_ingress_route_configs = {
        ("app1", "istio-ingress-route"): {
            "config": IstioIngressRouteConfig(
                model="model1",
                listeners=[http_listener, grpc_listener],
                http_routes=[
                    LibHTTPRoute(
                        name="http-route",
                        listener=http_listener,
                        backends=[LibBackendRef(service="svc", port=80)],
                        matches=[
                            LibHTTPRouteMatch(
                                path=LibHTTPPathMatch(type="PathPrefix", value="/api")
                            )
                        ],
                    )
                ],
                grpc_routes=[
                    LibGRPCRoute(
                        name="grpc-route",
                        listener=grpc_listener,
                        backends=[LibBackendRef(service="grpc-svc", port=9000)],
                        matches=[LibGRPCRouteMatch(method=GRPCMethodMatch(service="MyService"))],
                    )
                ],
            )
        }
    }
    tls_secret_name = None

    listeners = normalize_istio_ingress_route_listeners(
        istio_ingress_route_configs, tls_secret_name
    )

    assert len(listeners) == 2
    http_listener_norm = [listener for listener in listeners if listener["port"] == 8080][0]
    grpc_listener_norm = [listener for listener in listeners if listener["port"] == 9090][0]

    assert http_listener_norm["gateway_protocol"] == "HTTP"
    assert http_listener_norm["tls_secret_name"] is None
    assert grpc_listener_norm["gateway_protocol"] == "HTTP"
    assert grpc_listener_norm["tls_secret_name"] is None


def test_normalize_istio_ingress_route_listeners_with_tls():
    """Test normalizing istio-ingress-route listeners with TLS converts to HTTPS."""
    http_listener = Listener(port=8080, protocol=ProtocolType.HTTP)
    grpc_listener = Listener(port=9090, protocol=ProtocolType.GRPC)

    istio_ingress_route_configs = {
        ("app1", "istio-ingress-route"): {
            "config": IstioIngressRouteConfig(
                model="model1",
                listeners=[http_listener, grpc_listener],
                http_routes=[
                    LibHTTPRoute(
                        name="http-route",
                        listener=http_listener,
                        backends=[LibBackendRef(service="svc", port=80)],
                        matches=[
                            LibHTTPRouteMatch(
                                path=LibHTTPPathMatch(type="PathPrefix", value="/api")
                            )
                        ],
                    )
                ],
                grpc_routes=[
                    LibGRPCRoute(
                        name="grpc-route",
                        listener=grpc_listener,
                        backends=[LibBackendRef(service="grpc-svc", port=9000)],
                        matches=[LibGRPCRouteMatch(method=GRPCMethodMatch(service="MyService"))],
                    )
                ],
            )
        }
    }
    tls_secret_name = "my-tls-secret"

    listeners = normalize_istio_ingress_route_listeners(
        istio_ingress_route_configs, tls_secret_name
    )

    # Should have 2 listeners converted to HTTPS: 8080 HTTPS, 9090 HTTPS
    assert len(listeners) == 2

    https_8080 = [listener for listener in listeners if listener["port"] == 8080][0]
    https_9090 = [listener for listener in listeners if listener["port"] == 9090][0]

    assert https_8080["gateway_protocol"] == "HTTPS"
    assert https_8080["tls_secret_name"] == "my-tls-secret"
    assert https_9090["gateway_protocol"] == "HTTPS"
    assert https_9090["tls_secret_name"] == "my-tls-secret"


def test_merge_listeners_with_duplicates():
    """Test merging listeners keeps first occurrence for each port/protocol."""
    listeners = [
        {"port": 80, "gateway_protocol": "HTTP", "tls_secret_name": None, "source_app": "app1"},
        {"port": 80, "gateway_protocol": "HTTP", "tls_secret_name": None, "source_app": "app2"},
        {
            "port": 443,
            "gateway_protocol": "HTTPS",
            "tls_secret_name": "tls",
            "source_app": "app1",
        },
    ]

    merged = deduplicate_listeners(listeners)

    # Should deduplicate port 80 HTTP to a single listener (first one)
    assert len(merged) == 2
    assert merged[0]["port"] == 80
    assert merged[0]["gateway_protocol"] == "HTTP"
    assert merged[0]["source_app"] == "app1"  # First occurrence wins

    assert merged[1]["port"] == 443
    assert merged[1]["gateway_protocol"] == "HTTPS"
    assert merged[1]["source_app"] == "app1"


def test_normalize_ipa_routes_with_strip_prefix():
    """Test normalizing IPA routes includes URLRewrite filter when strip_prefix is True."""
    ipa_relations = {
        ("app1", "ingress"): {
            "routes": [
                {
                    "prefix": "/app1",
                    "service_name": "svc1",
                    "port": 8080,
                    "namespace": "model1",
                    "strip_prefix": True,
                }
            ],
        }
    }
    is_tls_enabled = False
    ingress_app_name = "istio-ingress-k8s"

    http_routes = normalize_ipa_routes(ipa_relations, is_tls_enabled, ingress_app_name)

    assert len(http_routes) == 1
    route = http_routes[0]
    assert route["name"] == "svc1-httproute-http-80-istio-ingress-k8s"  # Name format: {service}-httproute-{section_name}-{ingress_app_name}
    assert route["listener_port"] == 80
    assert route["listener_protocol"] == "HTTP"
    assert len(route["filters"]) == 1
    assert route["filters"][0].type == FilterType.URLRewrite


def test_normalize_ipa_routes_with_tls_creates_redirect():
    """Test normalizing IPA routes with TLS creates redirect and HTTPS routes."""
    ipa_relations = {
        ("app1", "ingress"): {
            "routes": [
                {
                    "prefix": "/app1",
                    "service_name": "svc1",
                    "port": 8080,
                    "namespace": "model1",
                    "strip_prefix": True,
                }
            ],
        }
    }
    is_tls_enabled = True
    ingress_app_name = "istio-ingress-k8s"

    http_routes = normalize_ipa_routes(ipa_relations, is_tls_enabled, ingress_app_name)

    # Should create 2 routes: HTTP redirect + HTTPS actual
    assert len(http_routes) == 2

    # First route should be HTTP redirect
    redirect_route = http_routes[0]
    assert redirect_route["name"] == "svc1-httproute-http-80-istio-ingress-k8s"
    assert redirect_route["listener_port"] == 80
    assert redirect_route["listener_protocol"] == "HTTP"
    assert len(redirect_route["backend_refs"]) == 0  # No backends for redirect
    assert len(redirect_route["filters"]) == 1
    assert redirect_route["filters"][0].type == FilterType.RequestRedirect
    assert redirect_route["filters"][0].requestRedirect.scheme == "https"
    assert redirect_route["filters"][0].requestRedirect.statusCode == 301

    # Second route should be HTTPS with backends
    https_route = http_routes[1]
    assert https_route["name"] == "svc1-httproute-https-443-istio-ingress-k8s"
    assert https_route["listener_port"] == 443
    assert https_route["listener_protocol"] == "HTTPS"
    assert len(https_route["backend_refs"]) == 1
    assert https_route["backend_refs"][0].name == "svc1"
    assert https_route["backend_refs"][0].port == 8080
    # Should have URLRewrite filter because strip_prefix=True
    assert len(https_route["filters"]) == 1
    assert https_route["filters"][0].type == FilterType.URLRewrite


def test_normalize_istio_ingress_route_http_and_grpc_routes():
    """Test normalizing istio-ingress-route converts library models to charm models."""
    http_listener = Listener(port=8080, protocol=ProtocolType.HTTP)
    grpc_listener = Listener(port=9090, protocol=ProtocolType.GRPC)

    istio_ingress_route_configs = {
        ("app1", "istio-ingress-route"): {
            "config": IstioIngressRouteConfig(
                model="model1",
                listeners=[http_listener, grpc_listener],
                http_routes=[
                    LibHTTPRoute(
                        name="http-route",
                        listener=http_listener,
                        backends=[LibBackendRef(service="http-svc", port=80)],
                        matches=[
                            LibHTTPRouteMatch(
                                path=LibHTTPPathMatch(type="PathPrefix", value="/api")
                            )
                        ],
                    )
                ],
                grpc_routes=[
                    LibGRPCRoute(
                        name="grpc-route",
                        listener=grpc_listener,
                        backends=[LibBackendRef(service="grpc-svc", port=9000)],
                        matches=[LibGRPCRouteMatch(method=GRPCMethodMatch(service="MyService"))],
                    )
                ],
            )
        }
    }
    is_tls_enabled = False
    ingress_app_name = "istio-ingress-k8s"

    http_routes = normalize_istio_ingress_route_http_routes(
        istio_ingress_route_configs, is_tls_enabled, ingress_app_name
    )
    grpc_routes = normalize_istio_ingress_route_grpc_routes(
        istio_ingress_route_configs, is_tls_enabled, ingress_app_name
    )

    # Verify HTTP route conversion
    assert len(http_routes) == 1
    http_route = http_routes[0]
    assert http_route["name"] == "app1-http-route-httproute-http-8080-istio-ingress-k8s"  # Route name format: {app}-{route.name}-httproute-{section_name}-{ingress_app_name}
    assert http_route["listener_port"] == 8080
    assert http_route["source_relation"] == "istio-ingress-route"
    assert len(http_route["matches"]) == 1

    # Verify gRPC route conversion
    assert len(grpc_routes) == 1
    grpc_route = grpc_routes[0]
    assert grpc_route["name"] == "app1-grpc-route-grpcroute-http-9090-istio-ingress-k8s"  # Route name format: {app}-{route.name}-grpcroute-{section_name}-{ingress_app_name}
    assert grpc_route["listener_port"] == 9090
    assert grpc_route["source_relation"] == "istio-ingress-route"
    assert len(grpc_route["matches"]) == 1


def test_get_unauthenticated_paths():
    """Test extracting unauthenticated paths from IPA includes wildcard suffixes."""
    application_route_data = {
        ("app1", "ingress-unauthenticated"): {
            "routes": [{"prefix": "/public"}],
        },
    }

    paths = get_unauthenticated_paths(application_route_data)

    # Should include both exact path and wildcard
    assert "/public" in paths
    assert "/public/*" in paths


def test_get_unauthenticated_paths_from_istio_ingress_route():
    """Test extracting unauthenticated paths from istio-ingress-route for HTTP and gRPC."""
    http_listener = Listener(port=8080, protocol=ProtocolType.HTTP)
    grpc_listener = Listener(port=9090, protocol=ProtocolType.GRPC)

    istio_ingress_route_configs = {
        ("app1", "istio-ingress-route-unauthenticated"): {
            "config": IstioIngressRouteConfig(
                model="model1",
                listeners=[http_listener, grpc_listener],
                http_routes=[
                    LibHTTPRoute(
                        name="public-http",
                        listener=http_listener,
                        backends=[LibBackendRef(service="svc", port=80)],
                        matches=[
                            LibHTTPRouteMatch(
                                path=LibHTTPPathMatch(type="PathPrefix", value="/api/public")
                            )
                        ],
                    )
                ],
                grpc_routes=[
                    LibGRPCRoute(
                        name="public-grpc",
                        listener=grpc_listener,
                        backends=[LibBackendRef(service="grpc-svc", port=9000)],
                        matches=[LibGRPCRouteMatch(method=GRPCMethodMatch(service="PublicService"))],
                    )
                ],
            )
        }
    }

    paths = get_unauthenticated_paths_from_istio_ingress_route_configs(
        istio_ingress_route_configs
    )

    # Should include HTTP paths with wildcards (both exact and wildcard)
    assert "/api/public" in paths
    assert "/api/public/*" in paths
    # For gRPC service without method, only wildcard is added
    assert "/PublicService/*" in paths
