# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes resource models."""

from ._gateway import (
    AllowedRoutes,
    BackendRef,
    GatewayClassSpec,
    GatewaySpec,
    GatewayTLSConfig,
    GRPCMethodMatch,
    GRPCRouteMatch,
    GRPCRouteResource,
    GRPCRouteResourceSpec,
    GRPCRouteRule,
    HTTPPathMatch,
    HTTPRouteMatch,
    HTTPRouteResource,
    HTTPRouteResourceSpec,
    HTTPRouteRule,
    IstioGatewayResource,
    IstioGatewaySpec,
    Listener,
    ParametersRef,
    ParentRef,
    SecretObjectReference,
)
from ._metadata import Metadata

__all__ = [
    "AllowedRoutes",
    "BackendRef",
    "GatewayClassSpec",
    "GatewaySpec",
    "GatewayTLSConfig",
    "GRPCMethodMatch",
    "GRPCRouteMatch",
    "GRPCRouteResource",
    "GRPCRouteResourceSpec",
    "GRPCRouteRule",
    "HTTPPathMatch",
    "HTTPRouteMatch",
    "HTTPRouteResource",
    "HTTPRouteResourceSpec",
    "HTTPRouteRule",
    "IstioGatewayResource",
    "IstioGatewaySpec",
    "Listener",
    "Metadata",
    "ParentRef",
    "ParametersRef",
    "SecretObjectReference",
]
