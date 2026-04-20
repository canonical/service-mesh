# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio-specific label reconciliation utilities."""

import json
import logging
from typing import Dict, Optional

import httpx
from lightkube import Client
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import ConfigMap, Service

logger = logging.getLogger(__name__)

label_configmap_name_template = "juju-service-mesh-{app_name}-labels"


def reconcile_charm_labels(
    client: Client,
    app_name: str,
    namespace: str,
    label_configmap_name: str,
    labels: Dict[str, str],
) -> None:
    """Reconcile user-defined Kubernetes labels on a Charm's Kubernetes objects.

    Manages labels on the charm's Pods (via StatefulSet) and Service. Uses a ConfigMap
    to track previously set labels so removed labels can be cleaned up.

    Args:
        client: The lightkube Client to use for Kubernetes API calls.
        app_name: The name of the application to reconcile labels for.
        namespace: The namespace in which the application is running.
        label_configmap_name: The name of the ConfigMap that stores the labels.
        labels: Labels to set. Previously set labels omitted here will be removed.
    """
    patch_labels: Dict[str, Optional[str]] = dict(labels)
    try:
        config_map = client.get(ConfigMap, label_configmap_name)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            config_map = _init_label_configmap(client, label_configmap_name, namespace)
        else:
            raise
    if config_map.data:
        config_map_labels = json.loads(config_map.data["labels"])
        for label in config_map_labels:
            if label not in patch_labels:
                patch_labels[label] = None

    client.patch(
        res=StatefulSet,
        name=app_name,
        obj={"spec": {"template": {"metadata": {"labels": patch_labels}}}},
    )
    client.patch(res=Service, name=app_name, obj={"metadata": {"labels": patch_labels}})

    config_map_labels = {k: v for k, v in patch_labels.items() if v is not None}
    config_map.data = {"labels": json.dumps(config_map_labels)}
    client.patch(res=ConfigMap, name=label_configmap_name, obj=config_map)


def _init_label_configmap(client: Client, name: str, namespace: str) -> ConfigMap:
    """Create a ConfigMap with data of {labels: {}}, returning the lightkube ConfigMap object."""
    obj = ConfigMap(
        data={"labels": "{}"},
        metadata=ObjectMeta(
            name=name,
            namespace=namespace,
        ),
    )
    client.create(obj=obj)
    return obj
