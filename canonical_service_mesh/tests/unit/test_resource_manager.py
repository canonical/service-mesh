# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import httpx
import pytest
from lightkube.generic_resource import create_global_resource, create_namespaced_resource
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod, Service

from canonical_service_mesh.k8s.resource_manager import KubernetesResourceManager
from canonical_service_mesh.k8s.resource_manager._resource_manager import (
    K8sApiError,
    _add_labels_to_resources,
    _get_resource_classes_in_manifests,
    _hash_lightkube_resource,
    _in_left_not_right,
    _validate_resources,
)

DEFAULT_LABELS = {"label": "default"}

test_namespaced = create_namespaced_resource("g1", "v1", "MyRes", "myress")
test_global = create_global_resource("g2", "v2", "MyGlobal", "myglobals")


@patch("canonical_service_mesh.k8s.resource_manager._resource_manager.apply_many")
def test_krm_apply_adds_labels(mocked_apply):
    resources = [Pod(metadata=ObjectMeta(name="p1", namespace="ns"))]
    krm = KubernetesResourceManager(
        labels=DEFAULT_LABELS, resource_types={Pod}, lightkube_client=MagicMock()
    )
    krm.apply(resources)

    mocked_apply.assert_called_once()
    applied = mocked_apply.call_args.kwargs["objs"]
    assert applied[0].metadata.labels["label"] == "default"


def test_krm_delete():
    krm = KubernetesResourceManager(
        labels=DEFAULT_LABELS, resource_types={Pod}, lightkube_client=MagicMock()
    )
    krm.get_deployed_resources = MagicMock(
        return_value=[Pod(metadata=ObjectMeta(name="p1", namespace="ns"))]
    )
    krm.delete()
    assert krm.lightkube_client.delete.call_count == 1


@pytest.mark.parametrize(
    "labels, resource_types, ctx",
    [
        (None, {Pod}, pytest.raises(ValueError)),
        ({}, {Pod}, pytest.raises(ValueError)),
        ({"l": "v"}, None, pytest.raises(ValueError)),
        ({"l": "v"}, set(), pytest.raises(ValueError)),
    ],
)
def test_krm_get_deployed_resources_requires_labels_and_types(labels, resource_types, ctx):
    krm = KubernetesResourceManager(
        labels=labels, resource_types=resource_types, lightkube_client=MagicMock()
    )
    with ctx:
        krm.get_deployed_resources()


@pytest.mark.parametrize(
    "method, kwargs",
    [
        ("apply", {"resources": [Pod(metadata=ObjectMeta(name="p", namespace="ns"))]}),
        ("delete", {}),
        ("get_deployed_resources", {}),
    ],
)
def test_krm_wraps_transport_error(method, kwargs):
    client = MagicMock()
    for attr in ("list", "apply", "patch", "delete"):
        setattr(client, attr, MagicMock(side_effect=httpx.ConnectTimeout("timeout")))

    krm = KubernetesResourceManager(
        labels=DEFAULT_LABELS, resource_types={Pod}, lightkube_client=client
    )
    with pytest.raises(K8sApiError, match="Kubernetes API may be unreachable"):
        getattr(krm, method)(**kwargs)


@patch("canonical_service_mesh.k8s.resource_manager._resource_manager.patch_many")
def test_krm_patch_adds_labels(mocked_patch):
    resources = [Pod(metadata=ObjectMeta(name="p1", namespace="ns"))]
    krm = KubernetesResourceManager(
        labels=DEFAULT_LABELS, resource_types={Pod}, lightkube_client=MagicMock()
    )
    krm.patch(resources)

    mocked_patch.assert_called_once()
    patched = mocked_patch.call_args.kwargs["objs"]
    assert patched[0].metadata.labels["label"] == "default"


@patch("canonical_service_mesh.k8s.resource_manager._resource_manager.delete_many")
@patch("canonical_service_mesh.k8s.resource_manager._resource_manager.patch_many")
def test_krm_reconcile_deletes_stale_and_patches_desired(mocked_patch, mocked_delete):
    existing = [
        Pod(metadata=ObjectMeta(name="old", namespace="ns")),
        Pod(metadata=ObjectMeta(name="keep", namespace="ns")),
    ]
    desired = [Pod(metadata=ObjectMeta(name="keep", namespace="ns"))]

    krm = KubernetesResourceManager(
        labels=DEFAULT_LABELS, resource_types={Pod}, lightkube_client=MagicMock()
    )
    krm.get_deployed_resources = MagicMock(return_value=existing)
    krm.reconcile(desired)

    mocked_delete.assert_called_once()
    deleted = mocked_delete.call_args.args[1]
    assert len(deleted) == 1
    assert deleted[0].metadata.name == "old"
    mocked_patch.assert_called_once()


@pytest.mark.parametrize(
    "resource, expected",
    [
        (
            StatefulSet(metadata=ObjectMeta(name="sts", namespace="ns")),
            ("apps", "v1", "StatefulSet", "sts", "ns"),
        ),
        (
            test_global(metadata=ObjectMeta(name="g1")),
            ("g2", "v2", "MyGlobal", "g1", None),
        ),
    ],
)
def test_hash_lightkube_resource(resource, expected):
    assert _hash_lightkube_resource(resource) == expected


def test_in_left_not_right():
    left = [1, 2, 3]
    right = [2, 3, 4]
    assert _in_left_not_right(left, right) == [1]


def test_in_left_not_right_with_hasher():
    a = StatefulSet(metadata=ObjectMeta(name="a", namespace="ns"))
    b = StatefulSet(metadata=ObjectMeta(name="b", namespace="ns"))
    result = _in_left_not_right([a, b], [b], hasher=_hash_lightkube_resource)
    assert len(result) == 1
    assert result[0].metadata.name == "a"


def test_add_labels_to_resources():
    resources = [
        Service(metadata=ObjectMeta(name="svc", namespace="ns")),
        StatefulSet(metadata=ObjectMeta(name="sts", namespace="ns", labels={"existing": "label"})),
    ]
    labeled = _add_labels_to_resources(resources, {"new": "label"})
    assert labeled[0].metadata.labels["new"] == "label"
    assert labeled[1].metadata.labels["existing"] == "label"
    assert labeled[1].metadata.labels["new"] == "label"


def test_get_resource_classes_in_manifests():
    resources = [
        Service(metadata=ObjectMeta(name="s", namespace="ns")),
        Pod(metadata=ObjectMeta(name="p", namespace="ns")),
        Service(metadata=ObjectMeta(name="s2", namespace="ns")),
    ]
    assert _get_resource_classes_in_manifests(resources) == {Service, Pod}


@pytest.mark.parametrize(
    "resources, allowed, ctx",
    [
        ([Pod(metadata=ObjectMeta(name="p", namespace="ns"))], {Pod}, nullcontext()),
        (
            [Pod(metadata=ObjectMeta(name="p", namespace="ns"))],
            {Service},
            pytest.raises(ValueError),
        ),
    ],
)
def test_validate_resources(resources, allowed, ctx):
    with ctx:
        _validate_resources(resources, allowed)
