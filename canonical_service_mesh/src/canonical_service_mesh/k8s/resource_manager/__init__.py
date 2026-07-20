# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes resource managers."""

from ._batch_operations import apply_many, delete_many, patch_many
from ._crd_manager import CustomResourceDefinitionManager
from ._mocking import FakeApiError
from ._resource_manager import (
    K8sApiError,
    KubernetesResourceManager,
    PolicyResourceManager,
    create_charm_default_labels,
)

__all__ = [
    "CustomResourceDefinitionManager",
    "FakeApiError",
    "K8sApiError",
    "KubernetesResourceManager",
    "PolicyResourceManager",
    "apply_many",
    "create_charm_default_labels",
    "delete_many",
    "patch_many",
]
