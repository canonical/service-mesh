# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio custom resource type definitions."""

from typing import Type

from lightkube.generic_resource import GenericNamespacedResource, create_namespaced_resource

AuthorizationPolicy: Type[GenericNamespacedResource] = create_namespaced_resource(
    "security.istio.io",
    "v1",
    "AuthorizationPolicy",
    "authorizationpolicies",
)
