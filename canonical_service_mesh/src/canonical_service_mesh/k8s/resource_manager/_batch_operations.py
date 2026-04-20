# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Batch operations for applying, patching, and deleting Kubernetes resources."""

import logging
from typing import Iterable, TypeVar, Union

import lightkube
from lightkube import sort_objects
from lightkube.core import resource
from lightkube.core.exceptions import ApiError
from lightkube.core.resource import GlobalResource, NamespacedResource
from lightkube.types import PatchType

LOGGER = logging.getLogger(__name__)

GlobalResourceTypeVar = TypeVar("GlobalResource", bound=resource.GlobalResource)
GlobalSubResourceTypeVar = TypeVar("GlobalSubResource", bound=resource.GlobalSubResource)
NamespacedResourceTypeVar = TypeVar("NamespacedSubResource", bound=resource.NamespacedResource)


def apply_many(
    client: lightkube.Client,
    objs: Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]],
    field_manager: str = None,
    force: bool = False,
    logger: logging.Logger = None,
) -> Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]]:
    """Create or configure an iterable of Lightkube objects using client.apply().

    Resources are sorted before applying to avoid referencing objects before they are created.

    Args:
        client: Lightkube client to use for applying resources.
        objs: Iterable of objects to create.
        field_manager: Name associated with the actor making these changes.
        force: Force apply requests, re-acquiring conflicting fields.
        logger: Logger to use for applying resources.

    Returns:
        A list of Resource objects returned from client.apply().
    """
    logger = logger or LOGGER
    objs = sort_objects(objs)
    returns = [None] * len(objs)

    for i, obj in enumerate(objs):
        if isinstance(obj, NamespacedResource):
            namespace = obj.metadata.namespace
        elif isinstance(obj, GlobalResource):
            namespace = None
        else:
            raise TypeError(
                f"apply_many only supports objects of types NamespacedResource or GlobalResource,"
                f" got {type(obj)}"
            )
        logger.debug(f"Creating {obj.__class__} {obj.metadata.name}...")
        returns[i] = client.apply(
            obj=obj, namespace=namespace, field_manager=field_manager, force=force
        )
    return returns


def patch_many(
    client: lightkube.Client,
    objs: Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]],
    patch_type: PatchType = PatchType.APPLY,
    field_manager: str = None,
    force: bool = False,
    logger: logging.Logger = None,
) -> Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]]:
    """Create or configure an iterable of Lightkube objects using client.patch().

    Similar to apply_many() but uses client.patch() with configurable patch_type.

    Args:
        client: Lightkube client to use for patching resources.
        objs: Iterable of objects to create.
        patch_type: Type of patch to use. Defaults to PatchType.APPLY.
        field_manager: Name associated with the actor making these changes.
        force: Force patch requests, re-acquiring conflicting fields.
        logger: Logger to use for patching resources.

    Returns:
        A list of Resource objects returned from client.patch().
    """
    logger = logger or LOGGER
    objs = sort_objects(objs)
    returns = [None] * len(objs)

    for i, obj in enumerate(objs):
        if isinstance(obj, NamespacedResource):
            namespace = obj.metadata.namespace
        elif isinstance(obj, GlobalResource):
            namespace = None
        else:
            raise TypeError(
                f"patch_many only supports objects of types NamespacedResource or GlobalResource,"
                f" got {type(obj)}"
            )
        logger.debug(f"Patching {obj.__class__} {obj.metadata.name}...")
        try:
            returns[i] = client.patch(
                res=obj.__class__,
                name=obj.metadata.name,
                obj=obj,
                namespace=namespace,
                patch_type=patch_type,
                field_manager=field_manager,
                force=force,
            )
        except ApiError as error:
            if error.status.code == 404 and patch_type != PatchType.APPLY:
                logger.debug(
                    f"Resource {obj.__class__} {obj.metadata.name} not found, creating with apply()..."
                )
                returns[i] = client.apply(
                    obj=obj, namespace=namespace, field_manager=field_manager, force=force
                )
            else:
                raise
    return returns


def delete_many(
    client: lightkube.Client,
    objs: Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]],
    ignore_missing: bool = True,
    logger: logging.Logger = None,
) -> None:
    """Delete an iterable of objects using client.delete().

    Resources are deleted in reverse order to avoid deleting objects that are being used.

    Args:
        client: Lightkube Client to use for deletions.
        objs: Iterable of objects to delete.
        ignore_missing: Avoid raising 404 errors on deletion.
        logger: Logger to use for deleting resources.
    """
    logger = logger or LOGGER
    objs = sort_objects(objs, reverse=True)
    exceptions = []

    for obj in objs:
        if isinstance(obj, NamespacedResource):
            namespace = obj.metadata.namespace
        elif isinstance(obj, GlobalResource):
            namespace = None
        else:
            raise TypeError(
                "delete_many only supports objects of types NamespacedResource or GlobalResource,"
                f" got {type(obj)}"
            )
        try:
            logger.debug(f"Deleting {obj.__class__} {obj.metadata.name}...")
            client.delete(res=obj.__class__, name=obj.metadata.name, namespace=namespace)
        except ApiError as error:
            if error.status.code == 404 and ignore_missing:
                logger.debug(
                    f"{obj.__class__} {obj.metadata.name} not found! Ignoring because"
                    f" ignore_missing={ignore_missing}."
                )
            else:
                logger.debug(f"Failed to delete {obj.__class__} {obj.metadata.name}: {error}")
                exceptions.append(error)

    if exceptions:
        raise RuntimeError("Deleting K8s resources completed with errors", exceptions)
