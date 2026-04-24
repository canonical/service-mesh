# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from lightkube.core.exceptions import ApiError
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Namespace, Pod
from lightkube.types import PatchType

from canonical_service_mesh.k8s.resource_manager._batch_operations import (
    apply_many,
    delete_many,
    patch_many,
)


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_apply_many_namespaced_and_global(mock_sort):
    mock_sort.side_effect = lambda objs: objs
    client = MagicMock()

    ns_resource = StatefulSet(metadata=ObjectMeta(name="sts", namespace="ns1"))
    global_resource = Namespace(metadata=ObjectMeta(name="myns"))

    result = apply_many(client=client, objs=[ns_resource, global_resource], force=True)

    assert len(result) == 2
    calls = client.apply.call_args_list
    assert calls[0].kwargs["namespace"] == "ns1"
    assert calls[1].kwargs["namespace"] is None


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_apply_many_rejects_invalid_type(mock_sort):
    mock_sort.side_effect = lambda objs: objs
    with pytest.raises(TypeError, match="NamespacedResource or GlobalResource"):
        apply_many(client=MagicMock(), objs=["not-a-resource"])


def _make_api_error(code):
    """Create a lightkube ApiError with the given status code."""
    return ApiError(status={"code": code, "message": f"Error {code}"})


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_delete_many_ignores_404(mock_sort):
    mock_sort.side_effect = lambda objs, reverse: objs
    client = MagicMock()
    client.delete.side_effect = _make_api_error(404)

    pod = Pod(metadata=ObjectMeta(name="p1", namespace="ns1"))
    delete_many(client=client, objs=[pod], ignore_missing=True)
    # Should not raise


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_delete_many_collects_non_404_errors(mock_sort):
    mock_sort.side_effect = lambda objs, reverse: objs
    client = MagicMock()
    client.delete.side_effect = _make_api_error(500)

    pod = Pod(metadata=ObjectMeta(name="p1", namespace="ns1"))
    with pytest.raises(RuntimeError, match="completed with errors"):
        delete_many(client=client, objs=[pod])


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_patch_many_patches_namespaced_resource(mock_sort):
    """patch_many calls client.patch with the correct namespace."""
    mock_sort.side_effect = lambda objs: objs
    client = MagicMock()
    pod = Pod(metadata=ObjectMeta(name="p1", namespace="ns1"))

    result = patch_many(client=client, objs=[pod])
    assert len(result) == 1
    client.patch.assert_called_once()
    assert client.patch.call_args.kwargs["namespace"] == "ns1"


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_patch_many_falls_back_to_apply_on_404_for_non_apply_patch(mock_sort):
    """When using MERGE patch and resource doesn't exist, falls back to apply."""
    mock_sort.side_effect = lambda objs: objs
    client = MagicMock()
    client.patch.side_effect = _make_api_error(404)

    pod = Pod(metadata=ObjectMeta(name="p1", namespace="ns1"))
    patch_many(client=client, objs=[pod], patch_type=PatchType.MERGE)

    client.apply.assert_called_once()


@patch("canonical_service_mesh.k8s.resource_manager._batch_operations.sort_objects")
def test_patch_many_reraises_404_for_apply_patch_type(mock_sort):
    """When using APPLY patch type, 404 is not caught — it re-raises."""
    mock_sort.side_effect = lambda objs: objs
    client = MagicMock()
    client.patch.side_effect = _make_api_error(404)

    pod = Pod(metadata=ObjectMeta(name="p1", namespace="ns1"))
    with pytest.raises(ApiError):
        patch_many(client=client, objs=[pod], patch_type=PatchType.APPLY)
