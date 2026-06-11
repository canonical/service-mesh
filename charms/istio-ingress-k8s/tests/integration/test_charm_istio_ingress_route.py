# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import lightkube
import pytest
import yaml
from helpers import (
    get_auth_policy_spec,
    get_ca_certificate,
    get_grpc_route_condition,
    get_http_response,
    get_k8s_service_address,
    get_route_condition,
    get_route_spec,
    send_grpc_request,
    send_grpc_request_with_tls,
    send_http_request,
    send_http_request_with_custom_ca,
)
from jubilant import Juju, all_active
from lightkube.generic_resource import create_namespaced_resource

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
TESTER_HTTP = "tester-http"
TESTER_GRPC = "tester-grpc"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deployment")
def test_deployment(juju: Juju, istio_core_juju: Juju, istio_ingress_charm, resources):
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_deploy_testers", depends=["test_deployment"])
def test_deploy_testers(juju: Juju, tester_http_charm, tester_grpc_charm):
    """Deploy HTTP tester, gRPC tester, and self-signed-certificates charms."""
    juju.deploy(
        tester_http_charm,
        app=TESTER_HTTP,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.deploy(
        tester_grpc_charm, app=TESTER_GRPC, resources={"grpc-server-image": "moul/grpcbin:latest"}
    )
    juju.deploy("self-signed-certificates", app="self-signed-certificates")
    juju.wait(
        lambda s: all_active(s, TESTER_HTTP, TESTER_GRPC, "self-signed-certificates"),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_relate_tester_http", depends=["test_deploy_testers"])
def test_relate_tester_http(juju: Juju):
    """Relate tester-http to istio-ingress-k8s via istio-ingress-route."""
    juju.integrate(f"{TESTER_HTTP}:istio-ingress-route", f"{APP_NAME}:istio-ingress-route")
    juju.wait(
        lambda s: all_active(s, APP_NAME, TESTER_HTTP),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_relate_tester_grpc", depends=["test_deploy_testers"])
def test_relate_tester_grpc(juju: Juju):
    """Relate tester-grpc to istio-ingress-k8s via istio-ingress-route."""
    juju.integrate(f"{TESTER_GRPC}:istio-ingress-route", f"{APP_NAME}:istio-ingress-route")
    juju.wait(
        lambda s: all_active(s, APP_NAME, TESTER_GRPC),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_http_routes_validity", depends=["test_relate_tester_http"])
def test_http_routes_validity(juju: Juju):
    """Test that HTTP routes from tester-http are correctly configured."""
    gateway_resource = create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    )
    c = lightkube.Client()
    gateway = c.get(gateway_resource, namespace=juju.model, name="istio-ingress-k8s")

    # Find the http-8080 listener
    listener_condition = next(
        (listener for listener in gateway.status["listeners"] if listener["name"] == "http-8080"),
        None,
    )
    listener_spec = next(
        (listener for listener in gateway.spec["listeners"] if listener["name"] == "http-8080"),
        None,
    )
    assert listener_condition is not None, "Listener http-8080 not found in Gateway status"
    assert listener_spec is not None, "Listener http-8080 not found in Gateway spec"

    # Should have 3 HTTP routes attached (api-route, health-route, and rewrite-route from tester-http)
    assert listener_condition["attachedRoutes"] == 3
    assert listener_condition["conditions"][0]["message"] == "No errors found"
    assert listener_condition["conditions"][0]["reason"] == "Accepted"
    assert listener_spec["port"] == 8080
    assert listener_spec["protocol"] == "HTTP"

    # Test api-route
    api_route_name = f"{TESTER_HTTP}-api-route-httproute-http-8080-{APP_NAME}"
    api_route_condition = get_route_condition(juju.model, api_route_name)
    assert api_route_condition["conditions"][0]["message"] == "Route was valid"
    assert api_route_condition["conditions"][0]["reason"] == "Accepted"
    assert api_route_condition["controllerName"] == "istio.io/gateway-controller"

    # Test health-route
    health_route_name = f"{TESTER_HTTP}-health-route-httproute-http-8080-{APP_NAME}"
    health_route_condition = get_route_condition(juju.model, health_route_name)
    assert health_route_condition["conditions"][0]["message"] == "Route was valid"
    assert health_route_condition["conditions"][0]["reason"] == "Accepted"

    # Test rewrite-route
    rewrite_route_name = f"{TESTER_HTTP}-rewrite-route-httproute-http-8080-{APP_NAME}"
    rewrite_route_condition = get_route_condition(juju.model, rewrite_route_name)
    assert rewrite_route_condition["conditions"][0]["message"] == "Route was valid"
    assert rewrite_route_condition["conditions"][0]["reason"] == "Accepted"

    # Verify the http-9090 listener exists (extra-port-route from tester-http for multi-port testing)
    listener_9090_condition = next(
        (listener for listener in gateway.status["listeners"] if listener["name"] == "http-9090"),
        None,
    )
    listener_9090_spec = next(
        (listener for listener in gateway.spec["listeners"] if listener["name"] == "http-9090"),
        None,
    )
    assert listener_9090_condition is not None, "Listener http-9090 not found in Gateway status"
    assert listener_9090_spec is not None, "Listener http-9090 not found in Gateway spec"
    assert listener_9090_condition["attachedRoutes"] == 1
    assert listener_9090_spec["port"] == 9090
    assert listener_9090_spec["protocol"] == "HTTP"

    # Test extra-port-route on port 9090
    extra_route_name = f"{TESTER_HTTP}-extra-port-route-httproute-http-9090-{APP_NAME}"
    extra_route_condition = get_route_condition(juju.model, extra_route_name)
    assert extra_route_condition["conditions"][0]["message"] == "Route was valid"
    assert extra_route_condition["conditions"][0]["reason"] == "Accepted"


@pytest.mark.dependency(
    name="test_http_routes_connectivity", depends=["test_http_routes_validity"]
)
def test_http_routes_connectivity(juju: Juju):
    """Test that HTTP routes are accessible via the ingress gateway."""
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")

    # Test /api endpoint
    api_url = f"http://{istio_ingress_address}:8080/api"
    assert send_http_request(api_url), f"Failed to reach {api_url}"

    # Test /health endpoint
    health_url = f"http://{istio_ingress_address}:8080/health"
    assert send_http_request(health_url), f"Failed to reach {health_url}"


@pytest.mark.dependency(
    name="test_multi_port_auth_policy", depends=["test_http_routes_validity"]
)
def test_multi_port_auth_policy(juju: Juju):
    """Test that a single AuthorizationPolicy is created with all ports for a multi-port backend.

    The tester-http charm requests routes on ports 8080 and 9090 pointing to the same backend
    service. The ingress charm should aggregate these into a single L4 AuthorizationPolicy
    containing both ports, rather than creating separate policies that overwrite each other.
    """
    policy_name = f"{TESTER_HTTP}-{APP_NAME}-{juju.model}-l4"
    policy_spec = get_auth_policy_spec(juju.model, policy_name)

    assert policy_spec is not None, f"AuthorizationPolicy '{policy_name}' not found."

    # Validate that both ports are present in a single policy
    rules = policy_spec["rules"]
    assert len(rules) == 1, "Expected exactly one rule in AuthorizationPolicy spec."

    ports = rules[0]["to"][0]["operation"]["ports"]
    assert sorted(ports) == ["8080", "9090"], (
        f"Expected ports ['8080', '9090'] in AuthorizationPolicy, got {sorted(ports)}. "
        "Multi-port aggregation may not be working correctly."
    )

    # Verify selector targets the tester-http app
    match_labels = policy_spec["selector"]["matchLabels"]
    assert match_labels.get("app.kubernetes.io/name") == TESTER_HTTP


@pytest.mark.dependency(
    name="test_http_route_urlrewrite_filter", depends=["test_http_routes_validity"]
)
def test_http_route_urlrewrite_filter(juju: Juju):
    """Test that URLRewrite filter correctly rewrites request paths."""
    route_name = f"{TESTER_HTTP}-rewrite-route-httproute-http-8080-{APP_NAME}"
    route_spec = get_route_spec(juju.model, route_name)

    # Verify filter exists and is configured correctly
    assert route_spec is not None, f"HTTPRoute {route_name} not found"
    assert "rules" in route_spec and len(route_spec["rules"]) > 0
    rule = route_spec["rules"][0]
    assert rule.get("filters") and len(rule["filters"]) == 1
    filter_spec = rule["filters"][0]
    assert filter_spec["type"] == "URLRewrite"
    assert filter_spec["urlRewrite"]["path"]["type"] == "ReplacePrefixMatch"
    assert filter_spec["urlRewrite"]["path"]["replacePrefixMatch"] == "/api"

    # Test end-to-end: verify echo server receives rewritten path
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")
    response = get_http_response(f"http://{istio_ingress_address}:8080/old-api/test")
    assert response.status_code == 200, (
        f"Request failed with status {response.status_code}: {response.text}"
    )

    # Echo server returns plain text with request details
    # Second line contains the method and path, e.g., "GET /api/test HTTP/1.1"
    lines = response.text.strip().split("\n")
    request_line = lines[2] if len(lines) > 2 else ""
    assert "/api/test" in request_line, (
        f"Expected rewritten path '/api/test' in request line, got: {request_line}"
    )


@pytest.mark.dependency(name="test_grpc_routes_validity", depends=["test_relate_tester_grpc"])
def test_grpc_routes_validity(juju: Juju):
    """Test that gRPC routes from tester-grpc are correctly configured."""
    gateway_resource = create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    )
    c = lightkube.Client()
    gateway = c.get(gateway_resource, namespace=juju.model, name="istio-ingress-k8s")

    # Find the http-9000 listener
    listener_condition = next(
        (listener for listener in gateway.status["listeners"] if listener["name"] == "http-9000"),
        None,
    )
    listener_spec = next(
        (listener for listener in gateway.spec["listeners"] if listener["name"] == "http-9000"),
        None,
    )
    assert listener_condition is not None, "Listener http-9000 not found in Gateway status"
    assert listener_spec is not None, "Listener http-9000 not found in Gateway spec"

    # Should have 3 gRPC routes attached (empty-route, headersunary-route, reflection-route from tester-grpc)
    assert listener_condition["attachedRoutes"] == 3
    assert listener_condition["conditions"][0]["message"] == "No errors found"
    assert listener_condition["conditions"][0]["reason"] == "Accepted"
    assert listener_spec["port"] == 9000
    assert listener_spec["protocol"] == "HTTP"

    # Test empty-route
    empty_route_name = f"{TESTER_GRPC}-empty-route-grpcroute-http-9000-{APP_NAME}"
    empty_route_condition = get_grpc_route_condition(juju.model, empty_route_name)
    assert empty_route_condition["conditions"][0]["message"] == "Route was valid"
    assert empty_route_condition["conditions"][0]["reason"] == "Accepted"
    assert empty_route_condition["controllerName"] == "istio.io/gateway-controller"

    # Test headersunary-route
    headersunary_route_name = f"{TESTER_GRPC}-headersunary-route-grpcroute-http-9000-{APP_NAME}"
    headersunary_route_condition = get_grpc_route_condition(juju.model, headersunary_route_name)
    assert headersunary_route_condition["conditions"][0]["message"] == "Route was valid"
    assert headersunary_route_condition["conditions"][0]["reason"] == "Accepted"

    # Test reflection-route
    reflection_route_name = f"{TESTER_GRPC}-reflection-route-grpcroute-http-9000-{APP_NAME}"
    reflection_route_condition = get_grpc_route_condition(juju.model, reflection_route_name)
    assert reflection_route_condition["conditions"][0]["message"] == "Route was valid"
    assert reflection_route_condition["conditions"][0]["reason"] == "Accepted"


@pytest.mark.dependency(
    name="test_grpc_routes_connectivity", depends=["test_grpc_routes_validity"]
)
def test_grpc_routes_connectivity(juju: Juju):
    """Test that gRPC routes are accessible via the ingress gateway."""
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")

    # Test Empty method (takes EmptyMessage)
    assert send_grpc_request(istio_ingress_address, 9000, "grpcbin.GRPCBin", "Empty"), (
        "Failed to call grpcbin.GRPCBin/Empty"
    )

    # Test HeadersUnary method (takes EmptyMessage)
    assert send_grpc_request(istio_ingress_address, 9000, "grpcbin.GRPCBin", "HeadersUnary"), (
        "Failed to call grpcbin.GRPCBin/HeadersUnary"
    )


@pytest.mark.dependency(name="test_relate_certificates", depends=["test_grpc_routes_connectivity"])
def test_relate_certificates(juju: Juju):
    """Relate self-signed-certificates to istio-ingress-k8s and configure external_hostname."""
    juju.integrate("self-signed-certificates:certificates", f"{APP_NAME}:certificates")

    # Configure external_hostname to enable TLS
    juju.config(APP_NAME, {"external_hostname": "test.example.com"})
    juju.wait(
        lambda s: all_active(s, APP_NAME, "self-signed-certificates"),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_tls_http_routes_validity", depends=["test_relate_certificates"])
def test_tls_http_routes_validity(juju: Juju):
    """Test that HTTP routes correctly upgrade to HTTPS listeners."""
    gateway_resource = create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    )
    c = lightkube.Client()
    gateway = c.get(gateway_resource, namespace=juju.model, name="istio-ingress-k8s")

    # Verify HTTPS listener for HTTP routes (port 8080 -> https-8080)
    https_8080_listener_condition = next(
        (listener for listener in gateway.status["listeners"] if listener["name"] == "https-8080"),
        None,
    )
    https_8080_listener_spec = next(
        (listener for listener in gateway.spec["listeners"] if listener["name"] == "https-8080"),
        None,
    )
    assert https_8080_listener_condition is not None, (
        "Listener https-8080 not found in Gateway status"
    )
    assert https_8080_listener_spec is not None, "Listener https-8080 not found in Gateway spec"
    assert https_8080_listener_condition["attachedRoutes"] == 3, (
        "Expected 3 HTTP routes attached to https-8080"
    )
    assert https_8080_listener_spec["port"] == 8080
    assert https_8080_listener_spec["protocol"] == "HTTPS"

    # Verify HTTP routes moved to HTTPS listener
    api_route_name = f"{TESTER_HTTP}-api-route-httproute-https-8080-{APP_NAME}"
    api_route_condition = get_route_condition(juju.model, api_route_name)
    assert api_route_condition["conditions"][0]["message"] == "Route was valid"
    assert api_route_condition["conditions"][0]["reason"] == "Accepted"
    health_route_name = f"{TESTER_HTTP}-health-route-httproute-https-8080-{APP_NAME}"
    health_route_condition = get_route_condition(juju.model, health_route_name)
    assert health_route_condition["conditions"][0]["message"] == "Route was valid"
    assert health_route_condition["conditions"][0]["reason"] == "Accepted"
    rewrite_route_name = f"{TESTER_HTTP}-rewrite-route-httproute-https-8080-{APP_NAME}"
    rewrite_route_condition = get_route_condition(juju.model, rewrite_route_name)
    assert rewrite_route_condition["conditions"][0]["message"] == "Route was valid"
    assert rewrite_route_condition["conditions"][0]["reason"] == "Accepted"


@pytest.mark.dependency(
    name="test_tls_http_routes_connectivity", depends=["test_tls_http_routes_validity"]
)
def test_tls_http_routes_connectivity(juju: Juju):
    """Test that HTTP routes are accessible via HTTPS."""
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")

    # Get CA certificate from certificate provider
    ca_cert = get_ca_certificate(juju, "self-signed-certificates/0")
    external_hostname = "test.example.com"

    # Test /api endpoint with TLS
    api_url = f"https://{external_hostname}:8080/api"
    assert (
        send_http_request_with_custom_ca(
            api_url, ca_cert, resolve_netloc_to_ip=istio_ingress_address
        )
        == 200
    ), f"Failed to reach {api_url} with TLS"

    # Test /health endpoint with TLS
    health_url = f"https://{external_hostname}:8080/health"
    assert (
        send_http_request_with_custom_ca(
            health_url, ca_cert, resolve_netloc_to_ip=istio_ingress_address
        )
        == 200
    ), f"Failed to reach {health_url} with TLS"


@pytest.mark.dependency(
    name="test_tls_grpc_routes_validity", depends=["test_tls_http_routes_connectivity"]
)
def test_tls_grpc_routes_validity(juju: Juju):
    """Test that gRPC routes correctly upgrade to HTTPS listeners."""
    gateway_resource = create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    )
    c = lightkube.Client()
    gateway = c.get(gateway_resource, namespace=juju.model, name="istio-ingress-k8s")

    # Verify HTTPS listener for gRPC routes (port 9000 -> https-9000)
    https_9000_listener_condition = next(
        (listener for listener in gateway.status["listeners"] if listener["name"] == "https-9000"),
        None,
    )
    https_9000_listener_spec = next(
        (listener for listener in gateway.spec["listeners"] if listener["name"] == "https-9000"),
        None,
    )
    assert https_9000_listener_condition is not None, (
        "Listener https-9000 not found in Gateway status"
    )
    assert https_9000_listener_spec is not None, "Listener https-9000 not found in Gateway spec"
    assert https_9000_listener_condition["attachedRoutes"] == 3, (
        "Expected 3 gRPC routes attached to https-9000"
    )
    assert https_9000_listener_spec["port"] == 9000
    assert https_9000_listener_spec["protocol"] == "HTTPS"

    # Verify gRPC routes moved to HTTPS listener
    empty_route_name = f"{TESTER_GRPC}-empty-route-grpcroute-https-9000-{APP_NAME}"
    empty_route_condition = get_grpc_route_condition(juju.model, empty_route_name)
    assert empty_route_condition["conditions"][0]["message"] == "Route was valid"
    assert empty_route_condition["conditions"][0]["reason"] == "Accepted"
    headersunary_route_name = f"{TESTER_GRPC}-headersunary-route-grpcroute-https-9000-{APP_NAME}"
    headersunary_route_condition = get_grpc_route_condition(juju.model, headersunary_route_name)
    assert headersunary_route_condition["conditions"][0]["message"] == "Route was valid"
    assert headersunary_route_condition["conditions"][0]["reason"] == "Accepted"
    reflection_route_name = f"{TESTER_GRPC}-reflection-route-grpcroute-https-9000-{APP_NAME}"
    reflection_route_condition = get_grpc_route_condition(juju.model, reflection_route_name)
    assert reflection_route_condition["conditions"][0]["message"] == "Route was valid"
    assert reflection_route_condition["conditions"][0]["reason"] == "Accepted"


@pytest.mark.dependency(
    name="test_tls_grpc_routes_connectivity", depends=["test_tls_grpc_routes_validity"]
)
def test_tls_grpc_routes_connectivity(juju: Juju):
    """Test that gRPC routes are accessible via HTTPS."""
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")

    # Get CA certificate from certificate provider
    ca_cert = get_ca_certificate(juju, "self-signed-certificates/0")
    external_hostname = "test.example.com"

    # Test Empty method with TLS
    assert send_grpc_request_with_tls(
        istio_ingress_address,
        9000,
        "grpcbin.GRPCBin",
        "Empty",
        ca_cert,
        hostname=external_hostname,
    ), "Failed to call grpcbin.GRPCBin/Empty with TLS"

    # Test HeadersUnary method with TLS
    assert send_grpc_request_with_tls(
        istio_ingress_address,
        9000,
        "grpcbin.GRPCBin",
        "HeadersUnary",
        ca_cert,
        hostname=external_hostname,
    ), "Failed to call grpcbin.GRPCBin/HeadersUnary with TLS"
