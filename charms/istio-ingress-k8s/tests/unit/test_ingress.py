# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import scenario
from canonical_service_mesh.models import (
    BackendRef,
    GRPCMethodMatch,
    GRPCRouteMatch,
    HTTPPathMatch,
    HTTPRouteMatch,
)
from charmlibs.interfaces.istio_ingress_route import (
    RequestRedirectFilter,
    RequestRedirectSpec,
)
from ops import ActiveStatus, BlockedStatus

from charm import IstioIngressCharm
from tests.unit.test_gateway import generate_certificates_relation
from utils import HTTPRoute, RouteInfo, get_unauthenticated_paths


def create_test_http_routes(routes_info, with_tls=False):
    """Create normalized HTTPRoute list for testing."""
    http_routes = []
    for route_info in routes_info:
        if with_tls:
            # When TLS is enabled, HTTP route (port 80) should be a redirect
            http_routes.append(
                HTTPRoute(
                    name=route_info["service_name"],
                    listener_port=80,
                    listener_protocol="HTTP",
                    namespace=route_info["namespace"],
                    source_app=route_info["service_name"],
                    source_relation="ingress",
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type="PathPrefix", value=route_info["prefix"])
                        )
                    ],
                    backend_refs=[],  # Redirects don't have backends
                    filters=[
                        RequestRedirectFilter(
                            requestRedirect=RequestRedirectSpec(scheme="https", statusCode=301)
                        )
                    ],
                )
            )
            # HTTPS route on port 443 with actual backend
            http_routes.append(
                HTTPRoute(
                    name=route_info["service_name"] + "-https",
                    listener_port=443,
                    listener_protocol="HTTPS",
                    namespace=route_info["namespace"],
                    source_app=route_info["service_name"],
                    source_relation="ingress",
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type="PathPrefix", value=route_info["prefix"])
                        )
                    ],
                    backend_refs=[
                        BackendRef(
                            name=route_info["service_name"],
                            port=route_info["port"],
                            namespace=route_info["namespace"],
                        )
                    ],
                    filters=[],
                )
            )
        else:
            # Without TLS, just create normal HTTP route on port 80
            http_routes.append(
                HTTPRoute(
                    name=route_info["service_name"],
                    listener_port=80,
                    listener_protocol="HTTP",
                    namespace=route_info["namespace"],
                    source_app=route_info["service_name"],
                    source_relation="ingress",
                    matches=[
                        HTTPRouteMatch(
                            path=HTTPPathMatch(type="PathPrefix", value=route_info["prefix"])
                        )
                    ],
                    backend_refs=[
                        BackendRef(
                            name=route_info["service_name"],
                            port=route_info["port"],
                            namespace=route_info["namespace"],
                        )
                    ],
                    filters=[],
                )
            )
    return http_routes


def test_construct_ingress_auth_policy(istio_ingress_charm, istio_ingress_context):
    """Test that the _construct_ingress_auth_policy method constructs an Authorization Policy object correctly."""
    target_name = "app-name"
    target_namespace = "app-namespace"
    target_ports = [80, 443]

    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        auth_policy = charm._construct_auth_policy_from_ingress_to_target(
            target_name=target_name,
            target_namespace=target_namespace,
            target_ports=target_ports,
        )

        # Verify the AuthorizationPolicy resource
        assert auth_policy.metadata.name == f"{target_name}-{charm.app.name}-{target_namespace}-l4"
        assert auth_policy.metadata.namespace == "app-namespace"

        # Check spec rules
        assert len(auth_policy.spec["rules"]) == 1
        rule = auth_policy.spec["rules"][0]

        # Verify `to` field
        assert rule["to"] == [{"operation": {"ports": ["80", "443"]}}]

        # Verify `from` field (principals)
        principals = rule["from"][0]["source"]["principals"]
        expected_principal = f"cluster.local/ns/{charm.model.name}/sa/{charm.managed_name}"
        assert principals == [expected_principal]

        # Verify workload selector
        assert auth_policy.spec["selector"] == {
            "matchLabels": {"app.kubernetes.io/name": "app-name"}
        }


def test_construct_auth_policies_multi_port_aggregation(istio_ingress_charm, istio_ingress_context):
    """Test that _construct_auth_policies aggregates multiple ports for the same backend into a single policy."""
    # Create routes that simulate the Tempo scenario: same service, different ports
    http_routes = [
        HTTPRoute(
            name="tempo-api",
            listener_port=80,
            listener_protocol="HTTP",
            namespace="cos",
            source_app="tempo",
            source_relation="istio-ingress-route",
            matches=[
                HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/tempo-api"))
            ],
            backend_refs=[BackendRef(name="tempo", port=3200, namespace="cos")],
            filters=[],
        ),
        HTTPRoute(
            name="tempo-otlp-http",
            listener_port=80,
            listener_protocol="HTTP",
            namespace="cos",
            source_app="tempo",
            source_relation="istio-ingress-route",
            matches=[
                HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/tempo-otlp"))
            ],
            backend_refs=[BackendRef(name="tempo", port=4318, namespace="cos")],
            filters=[],
        ),
        HTTPRoute(
            name="tempo-zipkin",
            listener_port=80,
            listener_protocol="HTTP",
            namespace="cos",
            source_app="tempo",
            source_relation="istio-ingress-route",
            matches=[
                HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/tempo-zipkin"))
            ],
            backend_refs=[BackendRef(name="tempo", port=9411, namespace="cos")],
            filters=[],
        ),
        # A different service in the same namespace with a single port
        HTTPRoute(
            name="grafana-route",
            listener_port=80,
            listener_protocol="HTTP",
            namespace="cos",
            source_app="grafana",
            source_relation="istio-ingress-route",
            matches=[
                HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/grafana"))
            ],
            backend_refs=[BackendRef(name="grafana", port=3000, namespace="cos")],
            filters=[],
        ),
    ]

    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        auth_policies = charm._construct_auth_policies(http_routes=http_routes, grpc_routes=[])

        # Should produce exactly 2 policies: one for tempo (3 ports aggregated), one for grafana
        assert len(auth_policies) == 2

        # Find the tempo policy
        tempo_policy = next(
            p for p in auth_policies
            if p.metadata.name == f"tempo-{charm.app.name}-cos-l4"
        )
        # All 3 ports should be aggregated into a single policy
        tempo_ports = tempo_policy.spec["rules"][0]["to"][0]["operation"]["ports"]
        assert sorted(tempo_ports) == ["3200", "4318", "9411"]

        # Find the grafana policy
        grafana_policy = next(
            p for p in auth_policies
            if p.metadata.name == f"grafana-{charm.app.name}-cos-l4"
        )
        grafana_ports = grafana_policy.spec["rules"][0]["to"][0]["operation"]["ports"]
        assert grafana_ports == ["3000"]

        # Verify both policies have correct namespace and selector
        assert tempo_policy.metadata.namespace == "cos"
        assert tempo_policy.spec["selector"]["matchLabels"]["app.kubernetes.io/name"] == "tempo"
        assert grafana_policy.metadata.namespace == "cos"
        assert grafana_policy.spec["selector"]["matchLabels"]["app.kubernetes.io/name"] == "grafana"


def test_construct_auth_policies_mixed_http_grpc(istio_ingress_charm, istio_ingress_context):
    """Test that _construct_auth_policies aggregates ports across HTTP and gRPC routes for the same backend."""
    http_routes = [
        HTTPRoute(
            name="myapp-http",
            listener_port=80,
            listener_protocol="HTTP",
            namespace="test-ns",
            source_app="myapp",
            source_relation="istio-ingress-route",
            matches=[
                HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value="/myapp"))
            ],
            backend_refs=[BackendRef(name="myapp", port=8080, namespace="test-ns")],
            filters=[],
        ),
    ]
    grpc_routes = [
        {
            "name": "myapp-grpc",
            "listener_port": 9000,
            "listener_protocol": "HTTP",
            "namespace": "test-ns",
            "source_app": "myapp",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(method=GRPCMethodMatch(service="myapp.Service", method="Call"))
            ],
            "backend_refs": [BackendRef(name="myapp", port=9000, namespace="test-ns")],
            "filters": [],
        },
    ]

    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        auth_policies = charm._construct_auth_policies(
            http_routes=http_routes, grpc_routes=grpc_routes
        )

        # Same backend (myapp, test-ns) from both HTTP and gRPC → single policy with both ports
        assert len(auth_policies) == 1
        ports = auth_policies[0].spec["rules"][0]["to"][0]["operation"]["ports"]
        assert sorted(ports) == ["8080", "9000"]


def generate_ingress_relation_data(
    name, model, port=80, ip="1.2.3.4", host=None, strip_prefix=False, endpoint="ingress"
):
    if host is None:
        host = f"{name}.example.com"
    return scenario.Relation(
        endpoint=endpoint,
        interface="ingress",
        remote_app_name=name,
        remote_app_data={
            "name": json.dumps(name),
            "model": json.dumps(model),
            "port": json.dumps(port),
            "strip-prefix": json.dumps(strip_prefix),
        },
        remote_units_data={
            0: {
                "host": json.dumps(host),
                "ip": json.dumps(ip),
            },
        },
    )


@pytest.mark.parametrize(
    "routes, expected_ingressed_prefixes",
    [
        # no relations
        ([], []),
        # with a single relation that has all data
        (
            [
                RouteInfo(
                    service_name="remote-app0",
                    namespace="remote-model0",
                    port=1234,
                    strip_prefix=False,
                    prefix="/path0",
                ),
            ],
            ["/path0"],
        ),
        # with multiple relations that have all data
        (
            [
                RouteInfo(
                    service_name="remote-app0",
                    namespace="remote-model0",
                    port=1234,
                    strip_prefix=False,
                    prefix="/path0",
                ),
                RouteInfo(
                    service_name="remote-app1",
                    namespace="remote-model1",
                    port=1234,
                    strip_prefix=False,
                    prefix="/path1",
                ),
            ],
            [
                "/path0",
                "/path1",
            ],
        ),
    ],
)
@patch(
    "charm.IstioIngressCharm._ingress_url", new_callable=PropertyMock, return_value="example.com"
)
def test_sync_ingress_resources(
    _mock_ingress_url,
    routes,
    expected_ingressed_prefixes,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test that the _sync_ingress_resources constructs HTTP routes when TLS is not configured."""
    # Mock Kubernetes Resource Managers
    mock_ingress_manager = MagicMock()
    mock_auth_manager = MagicMock()
    mock_ingress_manager_factory = MagicMock(return_value=mock_ingress_manager)
    mock_auth_manager_factory = MagicMock(return_value=mock_auth_manager)

    # Initialize charm in test scenario
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(
            leader=True,
        ),
    ) as manager:
        charm: IstioIngressCharm = manager.charm

        # Patch the managers into the charm
        charm._get_ingress_route_resource_manager = mock_ingress_manager_factory
        charm._get_ingress_auth_policy_resource_manager = mock_auth_manager_factory

        # Call the method under test
        http_routes = create_test_http_routes(routes)
        charm._sync_ingress_resources(http_routes=http_routes, grpc_routes=[])

        # Assertions: Managers' reconcile methods are called once
        mock_ingress_manager.reconcile.assert_called_once()
        mock_auth_manager.reconcile.assert_called_once()

        # Retrieve the resources passed to reconcile
        ingress_resources = mock_ingress_manager.reconcile.call_args[0][0]
        auth_resources = mock_auth_manager.reconcile.call_args.kwargs["raw_policies"]

        # Assertions: Check resource counts
        assert len(ingress_resources) == len(expected_ingressed_prefixes)
        assert len(auth_resources) == len(expected_ingressed_prefixes)

        # Assertions: Verify each ingress resource's structure
        for route, prefix in zip(ingress_resources, expected_ingressed_prefixes):
            assert len(route.spec["parentRefs"]) == 1
            assert route.spec["parentRefs"][0]["sectionName"] == "http-80"
            assert route.spec["rules"][0]["matches"][0]["path"]["value"] == prefix

        # Assertions: Verify authorization resources
        for auth in auth_resources:
            assert auth.metadata.name is not None
            assert auth.metadata.namespace is not None


@pytest.mark.parametrize(
    "routes, n_routes_expected",
    [
        # no relations
        ([], 0),
        # with a single relation that has all data
        (
            [
                RouteInfo(
                    service_name="remote-app0",
                    namespace="remote-model0",
                    port=1234,
                    strip_prefix=False,
                    prefix="/path0",
                ),
            ],
            2,
        ),
        # with multiple relations that have all data
        (
            [
                RouteInfo(
                    service_name="remote-app0",
                    namespace="remote-model0",
                    port=1234,
                    strip_prefix=False,
                    prefix="/path0",
                ),
                RouteInfo(
                    service_name="remote-app1",
                    namespace="remote-model1",
                    port=1234,
                    strip_prefix=False,
                    prefix="/path1",
                ),
            ],
            4,
        ),
    ],
)
@patch(
    "charm.IstioIngressCharm._ingress_url", new_callable=PropertyMock, return_value="example.com"
)
def test_sync_ingress_resources_with_tls(
    _mock_ingress_url,
    routes,
    n_routes_expected,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test that the _sync_ingress_resources constructs HTTP redirect and HTTPS routes when TLS is configured."""
    mock_krm = MagicMock()
    mock_krm_factory = MagicMock(return_value=mock_krm)

    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(
            relations=[generate_certificates_relation(subject="example.com")["relation"]],
            leader=True,
        ),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._get_ingress_route_resource_manager = mock_krm_factory
        http_routes = create_test_http_routes(routes, with_tls=True)
        charm._sync_ingress_resources(http_routes=http_routes, grpc_routes=[])

        # Assert that we've tried to reconcile the kubernetes resources
        charm._get_ingress_route_resource_manager().reconcile.assert_called_once()

        # Assert that _+_______________________
        resources = charm._get_ingress_route_resource_manager().reconcile.call_args[0][0]

        assert len(resources) == n_routes_expected
        # If TLS is configured, HTTP routes should be redirects and HTTPS routes should route to a parentRef
        for route in resources:
            if route.spec["parentRefs"][0]["sectionName"] == "http-80":
                assert len(route.spec["rules"]) == 1
                assert len(route.spec["rules"][0]["filters"]) == 1
                assert route.spec["rules"][0]["filters"][0]["type"] == "RequestRedirect"
            elif route.spec["parentRefs"][0]["sectionName"] == "https-443":
                assert len(route.spec["parentRefs"]) == 1
                assert route.spec["parentRefs"][0]["sectionName"] == "https-443"
            else:
                raise AssertionError("Unexpected section name")


@pytest.mark.parametrize(
    "ingress_relations, paths_expected",
    [
        # no relations
        ([], {}),
        # with a single relation that has all data
        (
            [generate_ingress_relation_data("remote-app0", "remote-model0")],
            # (app-name, ingress-relation-name): [list of paths for this app],
            {("remote-app0", "ingress"): ["/remote-model0-remote-app0"]},
        ),
        # with multiple related apps on `ingress`
        (
            [
                generate_ingress_relation_data("remote-app0", "remote-model0"),
                generate_ingress_relation_data("remote-app1", "remote-model1"),
                generate_ingress_relation_data("remote-app2", "remote-model2"),
            ],
            # (app-name, ingress-relation-name): [list of paths for this app],
            {
                ("remote-app0", "ingress"): ["/remote-model0-remote-app0"],
                ("remote-app1", "ingress"): ["/remote-model1-remote-app1"],
                ("remote-app2", "ingress"): ["/remote-model2-remote-app2"],
            },
        ),
        # with multiple related apps on `ingress` and `ingress-unauthenticated`
        (
            [
                generate_ingress_relation_data("remote-app0", "remote-model0"),
                generate_ingress_relation_data(
                    "remote-app1", "remote-model1", endpoint="ingress-unauthenticated"
                ),
                generate_ingress_relation_data("remote-app2", "remote-model2"),
            ],
            # (app-name, ingress-relation-name): [list of paths for this app],
            {
                ("remote-app0", "ingress"): ["/remote-model0-remote-app0"],
                ("remote-app1", "ingress-unauthenticated"): ["/remote-model1-remote-app1"],
                ("remote-app2", "ingress"): ["/remote-model2-remote-app2"],
            },
        ),
    ],
)
@patch(
    "charm.IstioIngressCharm._ingress_url", new_callable=PropertyMock, return_value="example.com"
)
def test_get_routes(
    _mock_ingress_url,
    ingress_relations,
    paths_expected,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test that .get_routes returns the expected routes for given ingress relations."""
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(
            relations=ingress_relations,
            leader=True,
        ),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        routes = charm._get_routes()

        # Extract the paths requested by these routes to compare to expected
        path_map_actual = {
            k: [r["prefix"] for r in route_data["routes"]] for k, route_data in routes.items()
        }
        assert path_map_actual == paths_expected


@pytest.mark.parametrize(
    "application_route_data, unauthenticated_paths_expected",
    [
        # no unauthenticated routes
        ({}, []),
        # one unauthenticated route
        (
            {
                ("remote-app0", "ingress-unauthenticated"): {
                    "routes": [{"prefix": "/remote-model0-remote-app0"}],
                },
            },
            ["/remote-model0-remote-app0", "/remote-model0-remote-app0/*"],
        ),
        # multiple unauthenticated routes
        (
            {
                ("remote-app0", "ingress-unauthenticated"): {
                    "routes": [{"prefix": "/remote-model0-remote-app0"}],
                },
                ("remote-app1", "ingress-unauthenticated"): {
                    "routes": [{"prefix": "/remote-model1-remote-app1"}],
                },
            },
            [
                "/remote-model0-remote-app0",
                "/remote-model0-remote-app0/*",
                "/remote-model1-remote-app1",
                "/remote-model1-remote-app1/*",
            ],
        ),
        # mixed ingress and ingress-unauthenticated
        (
            {
                ("remote-app0", "ingress"): {
                    "routes": [{"prefix": "/remote-model0-remote-app0"}],
                },
                ("remote-app1", "ingress-unauthenticated"): {
                    "routes": [{"prefix": "/remote-model1-remote-app1"}],
                },
                ("remote-app2", "ingress-unauthenticated"): {
                    "routes": [{"prefix": "/remote-model2-remote-app2"}],
                },
            },
            [
                "/remote-model1-remote-app1",
                "/remote-model1-remote-app1/*",
                "/remote-model2-remote-app2",
                "/remote-model2-remote-app2/*",
            ],
        ),
    ],
)
def test_get_unauthenticated_paths(application_route_data, unauthenticated_paths_expected):
    """Test that unauthenticated paths are extracted correctly with both exact and wildcard suffixes."""
    unauthenticated_paths_actual = get_unauthenticated_paths(application_route_data)
    assert sorted(unauthenticated_paths_actual) == sorted(unauthenticated_paths_expected)


@pytest.mark.parametrize(
    "ingress_relations, expected_ingress_data_sent, expected_final_status",
    [
        # Apps related to this charm on both ingress relations
        (
            # List of ingress relations, using either ingress endpoint
            (
                generate_ingress_relation_data("remote-app0", "remote-model0"),
                generate_ingress_relation_data(
                    "remote-app1", "remote-model1", endpoint="ingress-unauthenticated"
                ),
            ),
            # List of the "ingress" part of the ingress relation data that is sent by this charm to the remote app
            # Each row corresponds to a specific ingress relation in the previous tuple
            (
                {"ingress": json.dumps({"url": "http://example.com/remote-model0-remote-app0"})},
                {"ingress": json.dumps({"url": "http://example.com/remote-model1-remote-app1"})},
            ),
            ActiveStatus,
        ),
        # App is related to us on multiple ingress endpoints, requiring deduplication
        (
            (
                generate_ingress_relation_data("remote-app0", "remote-model0"),
                generate_ingress_relation_data(
                    "remote-app1", "remote-model1", endpoint="ingress-unauthenticated"
                ),
                generate_ingress_relation_data("remote-app2", "remote-model2"),
                generate_ingress_relation_data(
                    "remote-app2", "remote-model2", endpoint="ingress-unauthenticated"
                ),
            ),
            (
                {"ingress": json.dumps({"url": "http://example.com/remote-model0-remote-app0"})},
                {"ingress": json.dumps({"url": "http://example.com/remote-model1-remote-app1"})},
                {},  # removed because it is a duplicate
                {},  # removed because it is a duplicate
            ),
            BlockedStatus,
        ),
    ],
)
@patch("charm.IstioIngressCharm._is_ready", return_value=True)
@patch(
    "charm.IstioIngressCharm._ingress_url", new_callable=PropertyMock, return_value="example.com"
)
def test_ingress_e2e(
    _mock_ingress_url,
    _mock_is_ready,
    ingress_relations,
    expected_ingress_data_sent,
    expected_final_status,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test end-to-end operation of the charm with ingress relations.

    In particular, this test is important to assert that
    * we publish the ingress url back to related applications.
    * we handle duplicated ingress requests correctly (the charm does not break, but we do not provide an ingress)

    These functionalities are not tested elsewhere.
    """
    state_out = istio_ingress_context.run(
        istio_ingress_context.on.config_changed(),
        state=scenario.State(
            relations=ingress_relations,
            leader=True,
            containers=[
                scenario.Container(
                    "metrics-proxy",
                    can_connect=True,
                )
            ],
        ),
    )

    # Assert all relations have been told their ingress url
    for i, relation in enumerate(ingress_relations):
        assert state_out.get_relation(relation.id).local_app_data == expected_ingress_data_sent[i]

    assert isinstance(state_out.unit_status, expected_final_status)


def test_construct_grpc_destination_rules(istio_ingress_charm, istio_ingress_context):
    """Test that _construct_grpc_destination_rules creates DestinationRules correctly."""
    # Create test gRPC routes with some duplicate backends to test deduplication
    grpc_routes = [
        # Route 1: tester-grpc service on port 9000
        {
            "name": "tester-grpc-empty-route-grpcroute-http-9000-istio-ingress-k8s",
            "listener_port": 9000,
            "listener_protocol": "HTTP",
            "namespace": "test-namespace",
            "source_app": "tester-grpc",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(
                    method=GRPCMethodMatch(service="grpcbin.GRPCBin", method="Empty")
                )
            ],
            "backend_refs": [
                BackendRef(name="tester-grpc", port=9000, namespace="test-namespace")
            ],
            "filters": [],
        },
        # Route 2: Same service (duplicate backend - should be deduplicated)
        {
            "name": "tester-grpc-headersunary-route-grpcroute-http-9000-istio-ingress-k8s",
            "listener_port": 9000,
            "listener_protocol": "HTTP",
            "namespace": "test-namespace",
            "source_app": "tester-grpc",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(
                    method=GRPCMethodMatch(service="grpcbin.GRPCBin", method="HeadersUnary")
                )
            ],
            "backend_refs": [
                BackendRef(name="tester-grpc", port=9000, namespace="test-namespace")
            ],
            "filters": [],
        },
        # Route 3: Different service in different namespace
        {
            "name": "another-service-route-grpcroute-http-9001-istio-ingress-k8s",
            "listener_port": 9001,
            "listener_protocol": "HTTP",
            "namespace": "other-namespace",
            "source_app": "another-app",
            "source_relation": "istio-ingress-route",
            "matches": [
                GRPCRouteMatch(
                    method=GRPCMethodMatch(service="another.Service", method="Method")
                )
            ],
            "backend_refs": [
                BackendRef(name="another-service", port=9001, namespace="other-namespace")
            ],
            "filters": [],
        },
    ]

    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        destination_rules = charm._construct_grpc_destination_rules(grpc_routes)

        # Should create 2 DestinationRules (tester-grpc deduplicated, another-service)
        assert len(destination_rules) == 2

        # Find the tester-grpc DestinationRule
        tester_grpc_dr = next(
            dr for dr in destination_rules
            if dr.metadata.name == "tester-grpc-grpc-dest-rule-istio-ingress-k8s"
        )

        # Verify tester-grpc DestinationRule
        assert tester_grpc_dr.metadata.namespace == "test-namespace"
        assert tester_grpc_dr.spec["host"] == "tester-grpc.test-namespace.svc.cluster.local"
        assert tester_grpc_dr.spec["trafficPolicy"]["connectionPool"]["http"]["useClientProtocol"] is True

        # Find the another-service DestinationRule
        another_service_dr = next(
            dr for dr in destination_rules
            if dr.metadata.name == "another-service-grpc-dest-rule-istio-ingress-k8s"
        )

        # Verify another-service DestinationRule
        assert another_service_dr.metadata.namespace == "other-namespace"
        assert another_service_dr.spec["host"] == "another-service.other-namespace.svc.cluster.local"
        assert another_service_dr.spec["trafficPolicy"]["connectionPool"]["http"]["useClientProtocol"] is True
