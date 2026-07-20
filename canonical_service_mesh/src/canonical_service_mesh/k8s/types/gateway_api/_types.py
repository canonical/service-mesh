# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes Gateway API custom resource type definitions."""

from typing import Type

from lightkube.generic_resource import (
    GenericGlobalResource,
    GenericNamespacedResource,
    create_global_resource,
    create_namespaced_resource,
)

# GatewayClass is cluster-scoped in the Gateway API, so it must be a global
# resource; declaring it namespaced makes lightkube target a non-existent
# /namespaces/<ns>/gatewayclasses path (404).
GatewayClass: Type[GenericGlobalResource] = create_global_resource(
    "gateway.networking.k8s.io",
    "v1",
    "GatewayClass",
    "gatewayclasses",
)

Gateway: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.networking.k8s.io",
    "v1",
    "Gateway",
    "gateways",
)

HTTPRoute: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.networking.k8s.io",
    "v1",
    "HTTPRoute",
    "httproutes",
)

GRPCRoute: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.networking.k8s.io",
    "v1",
    "GRPCRoute",
    "grpcroutes",
)

ReferenceGrant: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.networking.k8s.io",
    "v1beta1",
    "ReferenceGrant",
    "referencegrants",
)
