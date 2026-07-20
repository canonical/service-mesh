# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy Gateway custom resource type definitions."""

from typing import Type

from lightkube.generic_resource import GenericNamespacedResource, create_namespaced_resource

EnvoyProxy: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.envoyproxy.io",
    "v1alpha1",
    "EnvoyProxy",
    "envoyproxies",
)

Backend: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.envoyproxy.io",
    "v1alpha1",
    "Backend",
    "backends",
)

SecurityPolicy: Type[GenericNamespacedResource] = create_namespaced_resource(
    "gateway.envoyproxy.io",
    "v1alpha1",
    "SecurityPolicy",
    "securitypolicies",
)
