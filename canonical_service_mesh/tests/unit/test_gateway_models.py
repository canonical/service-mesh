# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from canonical_service_mesh.models import (
    AllowedRoutes,
    BackendRef,
    GRPCRouteResource,
    GRPCRouteResourceSpec,
    HTTPPathMatch,
    HTTPRouteMatch,
    HTTPRouteResource,
    HTTPRouteResourceSpec,
    HTTPRouteRule,
    IstioGatewayResource,
    IstioGatewaySpec,
    Listener,
    Metadata,
    ParentRef,
)


def test_gateway_resource_roundtrip():
    gw = IstioGatewayResource(
        metadata=Metadata(name="my-gw", namespace="istio-system"),
        spec=IstioGatewaySpec(
            gatewayClassName="istio",
            listeners=[
                Listener(
                    name="http",
                    port=80,
                    protocol="HTTP",
                    allowedRoutes=AllowedRoutes(namespaces={"from": "All"}),
                )
            ],
        ),
    )
    data = gw.model_dump()
    restored = IstioGatewayResource.model_validate(data)
    assert restored.spec.gatewayClassName == "istio"
    assert restored.spec.listeners[0].port == 80


def test_http_route_resource():
    route = HTTPRouteResource(
        metadata=Metadata(name="my-route", namespace="default"),
        spec=HTTPRouteResourceSpec(
            parentRefs=[ParentRef(name="my-gw", namespace="istio-system", sectionName="http")],
            rules=[
                HTTPRouteRule(
                    matches=[HTTPRouteMatch(path=HTTPPathMatch(value="/api"))],
                    backendRefs=[BackendRef(name="backend", port=8080, namespace="default")],
                )
            ],
        ),
    )
    assert route.spec.rules[0].matches[0].path.type == "PathPrefix"
    assert route.spec.rules[0].backendRefs[0].port == 8080


def test_grpc_route_resource():
    route = GRPCRouteResource(
        metadata=Metadata(name="grpc-route", namespace="default"),
        spec=GRPCRouteResourceSpec(
            parentRefs=[ParentRef(name="my-gw", namespace="istio-system", sectionName="grpc")],
            rules=[],
        ),
    )
    assert route.metadata.name == "grpc-route"
    assert route.spec.parentRefs[0].sectionName == "grpc"
