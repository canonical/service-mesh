# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

# pyright: reportAttributeAccessIssue=false, reportOptionalIterable=false
# pyright: reportOperatorIssue=false, reportReturnType=false
# pyright: reportInvalidTypeForm=false, reportArgumentType=false
# Lightkube generic resource types and create_namespaced_resource() lack proper type stubs.

"""Resource managers for Kubernetes manifests and mesh policies."""

import copy
import functools
import logging
from typing import Callable, Dict, List, Optional, Set, Tuple, Type

import httpx
from lightkube import ApiError, Client
from lightkube.core.resource import NamespacedResource, Resource, api_info
from lightkube.types import PatchType
from ops import CharmBase

from ...enums import MeshType
from ...utils.istio._policy_builder import (
    POLICY_RESOURCE_TYPES,
    build_policy_resources_istio,
)
from ..types import (
    LightkubeResourcesList,
    LightkubeResourceType,
    LightkubeResourceTypesSet,
)
from ..types.istio import AuthorizationPolicy
from ._batch_operations import apply_many, delete_many, patch_many


def _k8s_api_call(func):
    """Catch transport-level errors from the Kubernetes API and wrap them in K8sApiError."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except httpx.TransportError as e:
            raise K8sApiError(
                f"Failed to {func.__name__} Kubernetes resources: "
                f"the Kubernetes API may be unreachable. Cause: {e}"
            ) from e

    return wrapper


class K8sApiError(Exception):
    """Raised when a Kubernetes API call fails due to a transport-level error."""


class KubernetesResourceManager:
    """Helper API to manage (create, update, delete) a manifest of Kubernetes resources."""

    def __init__(
        self,
        labels: Optional[dict],
        resource_types: LightkubeResourceTypesSet,
        lightkube_client: Client,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialise a KubernetesResourceManager.

        Args:
            labels: Label selector for all resources managed by this KRM.
            resource_types: Set of Lightkube Resource classes managed by this KRM.
            lightkube_client: Lightkube Client for all k8s operations.
            logger: Logger for log output.
        """
        self.labels = labels
        self.resource_types = resource_types
        self.lightkube_client = lightkube_client
        if logger is None:
            self.log = logging.getLogger(__name__)
        else:
            self.log = logger

    @_k8s_api_call
    def apply(self, resources: LightkubeResourcesList, force: bool = True):
        """Apply the provided Kubernetes resources using server-side apply.

        Args:
            resources: A list of Lightkube Resource objects to apply.
            force: Force apply requests.
        """
        self.log.info("Applying resources")
        if self.labels is not None:
            resources = _add_labels_to_resources(resources, self.labels)

        if self.resource_types:
            try:
                _validate_resources(resources, allowed_resource_types=self.resource_types)
            except ValueError as e:
                raise ValueError(
                    "Failed to validate resources before applying them. This likely means we tried"
                    " to create a resource of type not included in `KRM.resource_types`."
                ) from e

        apply_many(
            client=self.lightkube_client,
            objs=resources,
            force=force,
            logger=self.log,
        )

    @_k8s_api_call
    def patch(
        self,
        resources: LightkubeResourcesList,
        force: bool = True,
        patch_type: PatchType = PatchType.APPLY,
    ):
        """Patch the provided Kubernetes resources.

        Args:
            resources: A list of Lightkube Resource objects to patch.
            force: Force patch requests.
            patch_type: Type of patch to use.
        """
        self.log.info("Patching resources")
        if self.labels is not None:
            resources = _add_labels_to_resources(resources, self.labels)

        if self.resource_types:
            try:
                _validate_resources(resources, allowed_resource_types=self.resource_types)
            except ValueError as e:
                raise ValueError(
                    "Failed to validate resources before patching them. This likely means we tried"
                    " to create a resource of type not included in `KRM.resource_types`."
                ) from e

        patch_many(
            client=self.lightkube_client,
            objs=resources,
            patch_type=patch_type,
            force=force,
            logger=self.log,
        )

    @_k8s_api_call
    def delete(self, ignore_missing=True):
        """Delete all resources managed by this KubernetesResourceManager.

        Args:
            ignore_missing: Avoid raising 404 errors on deletion.
        """
        resources_to_delete = self.get_deployed_resources()
        delete_many(self.lightkube_client, resources_to_delete, ignore_missing, self.log)

    @_k8s_api_call
    def get_deployed_resources(self) -> LightkubeResourcesList:
        """Return a list of all deployed resources matching the label selector.

        Returns:
            A list of Lightkube Resource objects.
        """
        if self.labels is None or len(self.labels) == 0:
            raise ValueError("Cannot get_deployed_resources without a labelset defined")

        if self.resource_types is None or len(self.resource_types) == 0:
            raise ValueError("Cannot get_deployed_resources without one or more resource_types")

        resources = []
        for resource_type in self.resource_types:
            if issubclass(resource_type, NamespacedResource):
                namespace = "*"
            else:
                namespace = None
            try:
                resources.extend(
                    self.lightkube_client.list(
                        resource_type, namespace=namespace, labels=self.labels
                    )
                )
            except ApiError as error:
                if error.status.code == 404:
                    self.log.debug(
                        f"resource type {resource_type} not found in cluster. Ignoring this type."
                    )
                raise error

        return resources

    @_k8s_api_call
    def reconcile(
        self,
        resources: LightkubeResourcesList,
        force=True,
        ignore_missing=True,
        patch_type: PatchType = PatchType.APPLY,
    ):
        """Reconcile the given resources, removing, updating, or creating objects as required.

        Args:
            resources: A list of Lightkube Resource objects to apply.
            force: Force patch over managed resources.
            ignore_missing: Avoid raising 404 errors on deletion.
            patch_type: Type of patch to use.
        """
        desired_resources = resources
        existing_resources = self.get_deployed_resources()

        resources_to_delete = _in_left_not_right(
            existing_resources, desired_resources, hasher=_hash_lightkube_resource
        )
        delete_many(self.lightkube_client, resources_to_delete, ignore_missing, self.log)

        self.patch(resources=resources, force=force, patch_type=patch_type)


def create_charm_default_labels(application_name: str, model_name: str, scope: str) -> dict:
    """Return a default label style for the KubernetesResourceHandler label selector."""
    return {
        "app.kubernetes.io/instance": f"{application_name}-{model_name}",
        "kubernetes-resource-handler-scope": scope,
    }


def _add_label_field_to_resource(
    resource: LightkubeResourceType,
) -> LightkubeResourceType:
    """Add a metadata.labels field to a Lightkube resource."""
    as_dict = resource.to_dict()
    as_dict["metadata"]["labels"] = {}
    return resource.from_dict(as_dict)


def _add_labels_to_resources(resources: LightkubeResourcesList, labels: dict):
    """Return a copy of resources where each resource has the given labels added."""
    resources = copy.deepcopy(resources)

    for resource in resources:
        if resource.metadata.labels is None:
            resource.metadata.labels = {}

        if resource.metadata.labels is None:
            resource = _add_label_field_to_resource(resource)
        resource.metadata.labels.update(labels)
    return resources


def _get_resource_classes_in_manifests(
    resource_list: LightkubeResourcesList,
) -> LightkubeResourceTypesSet:
    """Return a set of the resource classes in a list of resources."""
    return {type(rsc) for rsc in resource_list}


def _hash_lightkube_resource(resource: Resource) -> Tuple[str, str, str, str, str]:
    """Hash a Lightkube Resource by returning a tuple of (group, version, kind, name, namespace)."""
    resource_info = api_info(resource).resource

    return (
        resource_info.group,
        resource_info.version,
        resource_info.kind,
        resource.metadata.name,
        resource.metadata.namespace,
    )


def _in_left_not_right(left: list, right: list, hasher: Optional[Callable] = None) -> list:
    """Return the items in left that are not right (the Set difference).

    Args:
        left: A list.
        right: A list.
        hasher: A function that hashes items to something immutable and comparable.

    Returns:
        A list of items in left that are not in right.
    """
    if hasher is None:
        hasher = hash

    left_as_dict = {hasher(resource): resource for resource in left}
    right_as_dict = {hasher(resource): resource for resource in right}

    keys_in_left_not_right = set(left_as_dict.keys()) - set(right_as_dict.keys())
    return [left_as_dict[k] for k in keys_in_left_not_right]


def _validate_resources(resources, allowed_resource_types: LightkubeResourceTypesSet):
    """Validate that the resources are of a type in the allowed_resource_types set."""
    resource_types = _get_resource_classes_in_manifests(resources)
    for resource_type in resource_types:
        if resource_type not in allowed_resource_types:
            raise ValueError(
                f"Resource type {resource_type} not in allowed resource types"
                f" '{allowed_resource_types}'"
            )


class PolicyResourceManager:
    """A mesh-agnostic policy resource manager that manages policy manifests in Kubernetes.

    Can be used by charms to create and manage their own policy resources for scenarios like
    using Canonical Service Mesh in a non-managed model, managing custom policies, or managing
    authorization policies between charms not related to the service mesh beacon.

    Args:
        charm: The charm instantiating this object.
        lightkube_client: Lightkube Client for all k8s operations.
        labels: Label selector for managed resources.
        logger: Logger for log output.
    """

    def __init__(
        self,
        charm: CharmBase,
        lightkube_client: Client,
        labels: Optional[Dict] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._app_name = charm.app.name
        self._model_name = charm.model.name
        resource_types = self._get_all_supported_policy_resource_types()

        if logger is None:
            self.log = logging.getLogger(__name__)
        else:
            self.log = logger
        self._krm = KubernetesResourceManager(
            labels=labels,
            resource_types=resource_types,
            lightkube_client=lightkube_client,
            logger=self.log,
        )

    @staticmethod
    def _get_all_supported_policy_resource_types() -> LightkubeResourceTypesSet:
        """Return all the resource types supported by the PRM class."""
        all_types: Set[Type] = set()
        for resource_types in POLICY_RESOURCE_TYPES.values():
            all_types.update(resource_types)
        return all_types

    @staticmethod
    def _get_policy_resource_builder(mesh_type: MeshType):
        """Return the policy resource builder for the given mesh type."""
        if mesh_type == MeshType.istio:
            return build_policy_resources_istio
        raise ValueError(
            f"PolicyResourceManager instantiated with an unknown mesh type: {mesh_type}. "
            f"Check Canonical Service Mesh documentation for currently supported mesh types."
        )

    def _build_policy_resources(
        self, policies: list, mesh_type: MeshType
    ) -> LightkubeResourcesList:
        """Build the Lightkube resources for the managed policies."""
        policy_resource_builder = self._get_policy_resource_builder(mesh_type)
        return policy_resource_builder(self._app_name, self._model_name, policies)

    def _validate_raw_policies(self, raw_policies: List[AuthorizationPolicy]) -> None:
        """Validate that raw_policies contain only supported resource types.

        Raises:
            TypeError: If a raw_policy is not of a supported type.
        """
        supported_types = self._get_all_supported_policy_resource_types()
        if not supported_types:
            raise RuntimeError(
                "No supported policy resource types found in PolicyResourceManager."
            )
        for policy in raw_policies:
            if type(policy) not in supported_types:
                self.log.error(
                    f"raw_policy of type '{type(policy).__name__}' is not a supported "
                    f"policy resource type."
                )
                raise TypeError(
                    f"raw_policy of type '{type(policy).__name__}' is not a supported "
                    f"policy resource type. "
                    f"Supported types: {[t.__name__ for t in supported_types]}"
                )

    def reconcile(
        self,
        policies: list,
        mesh_type: MeshType,
        raw_policies: Optional[List[AuthorizationPolicy]] = None,
        force: bool = True,
        ignore_missing: bool = True,
    ) -> None:
        """Reconcile the given policies, removing, updating, or creating objects as required.

        Args:
            policies: A list of MeshPolicy objects defining the required policy behaviour.
            mesh_type: The type of service mesh.
            raw_policies: Pre-built policy resources to merge with the built policies.
            force: Force apply over managed resources.
            ignore_missing: Avoid raising 404 errors on deletion.

        Raises:
            TypeError: If raw_policies contains resources of unsupported types.
        """
        if raw_policies:
            self._validate_raw_policies(raw_policies)

        all_resources: List = (
            list(self._build_policy_resources(policies, mesh_type)) if policies else []
        )
        if raw_policies:
            all_resources.extend(raw_policies)

        if not all_resources:
            self.delete(ignore_missing=ignore_missing)
            return

        self._krm.reconcile(all_resources, force=force, ignore_missing=ignore_missing)

    def delete(self, ignore_missing=True):
        """Delete all the policy resources handled by this manager.

        Args:
            ignore_missing: Avoid raising 404 errors on deletion.
        """
        try:
            self._krm.delete(ignore_missing=ignore_missing)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404 and ignore_missing:
                self.log.info("CRD not found, skipping deletion")
                return
            raise
