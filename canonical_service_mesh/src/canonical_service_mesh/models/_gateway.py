# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Gateway API resource models for Kubernetes."""

from typing import Dict, List, Optional

from pydantic import BaseModel

from ._metadata import Metadata


class AllowedRoutes(BaseModel):
    """AllowedRoutes defines namespaces from which traffic is allowed."""

    namespaces: Dict[str, str]


class SecretObjectReference(BaseModel):
    """SecretObjectReference defines a reference to a Kubernetes secret."""

    group: Optional[str] = None
    kind: Optional[str] = None
    name: str
    namespace: Optional[str] = None


class GatewayTLSConfig(BaseModel):
    """GatewayTLSConfig defines the TLS configuration for a listener."""

    certificateRefs: Optional[List[SecretObjectReference]] = None  # noqa: N815


class Listener(BaseModel):
    """Listener defines a port and protocol configuration."""

    name: str
    port: int
    protocol: str
    allowedRoutes: AllowedRoutes  # noqa: N815
    hostname: Optional[str] = None
    tls: Optional[GatewayTLSConfig] = None


class ParametersRef(BaseModel):
    """ParametersRef references an implementation-specific resource for GatewayClass config."""

    group: str
    kind: str
    name: str
    namespace: Optional[str] = None


class GatewayClassSpec(BaseModel):
    """GatewayClassSpec defines the specification of a GatewayClass resource."""

    controllerName: str  # noqa: N815
    parametersRef: Optional[ParametersRef] = None  # noqa: N815


class GatewaySpec(BaseModel):
    """Generic GatewaySpec for any Gateway API implementation."""

    gatewayClassName: str  # noqa: N815
    listeners: List[Listener]
    parametersRef: Optional[ParametersRef] = None  # noqa: N815


# TODO: remove IstioGatewaySpec and IstioGatewayResource — use GatewaySpec instead.
# Tracked in specs/envoy.spec.md Discussion Points.
class IstioGatewaySpec(BaseModel):
    """GatewaySpec defines the specification of a gateway."""

    gatewayClassName: str  # noqa: N815
    listeners: List[Listener]


class IstioGatewayResource(BaseModel):
    """GatewayResource defines the structure of a Gateway Kubernetes resource."""

    metadata: Metadata
    spec: IstioGatewaySpec


class ParentRef(BaseModel):
    """ParentRef specifies the parent gateway resource for this route."""

    name: str
    namespace: str
    sectionName: str  # noqa: N815


class BackendRef(BaseModel):
    """BackendRef specifies the backend service reference that traffic will be routed to."""

    name: str
    port: int
    namespace: str


class HTTPPathMatch(BaseModel):
    """HTTPPathMatch defines the type and value of path matching."""

    type: str = "PathPrefix"
    value: str


class HTTPRouteMatch(BaseModel):
    """HTTPRouteMatch defines the path matching configuration."""

    path: HTTPPathMatch


class HTTPRouteRule(BaseModel):
    """HTTPRouteRule defines the routing rule configuration."""

    matches: List[HTTPRouteMatch]
    backendRefs: Optional[List[BackendRef]] = []  # noqa: N815
    filters: Optional[list] = []


class HTTPRouteResourceSpec(BaseModel):
    """HTTPRouteResourceSpec defines the specification of an HTTPRoute Kubernetes resource."""

    parentRefs: List[ParentRef]  # noqa: N815
    rules: List[HTTPRouteRule]


class HTTPRouteResource(BaseModel):
    """HTTPRouteResource defines the structure of an HTTPRoute Kubernetes resource."""

    metadata: Metadata
    spec: HTTPRouteResourceSpec


class GRPCMethodMatch(BaseModel):
    """GRPCMethodMatch defines the gRPC method matching configuration."""

    service: Optional[str] = None
    method: Optional[str] = None


class GRPCRouteMatch(BaseModel):
    """GRPCRouteMatch defines the matching configuration for gRPC routes."""

    method: Optional[GRPCMethodMatch] = None


class GRPCRouteRule(BaseModel):
    """GRPCRouteRule defines the routing rule configuration for gRPC routes."""

    matches: Optional[List[GRPCRouteMatch]] = None
    backendRefs: Optional[List[BackendRef]] = []  # noqa: N815
    filters: Optional[list] = []


class GRPCRouteResourceSpec(BaseModel):
    """GRPCRouteResourceSpec defines the specification of a GRPCRoute Kubernetes resource."""

    parentRefs: List[ParentRef]  # noqa: N815
    rules: List[GRPCRouteRule]


class GRPCRouteResource(BaseModel):
    """GRPCRouteResource defines the structure of a GRPCRoute Kubernetes resource."""

    metadata: Metadata
    spec: GRPCRouteResourceSpec
