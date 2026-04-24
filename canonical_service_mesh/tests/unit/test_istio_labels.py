# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for reconcile_charm_labels and _init_label_configmap."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import ConfigMap, Service

from canonical_service_mesh.utils.istio._labels import (
    _init_label_configmap,
    reconcile_charm_labels,
)


def _make_http_status_error(status_code):
    """Create an httpx.HTTPStatusError with the given status code."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    return httpx.HTTPStatusError(
        message=f"Error {status_code}", request=MagicMock(), response=response
    )


def test_init_label_configmap_creates_with_empty_labels():
    client = MagicMock()
    result = _init_label_configmap(client, "my-cm", "my-ns")

    client.create.assert_called_once()
    created = client.create.call_args.kwargs["obj"]
    assert created.metadata.name == "my-cm"
    assert created.metadata.namespace == "my-ns"
    assert json.loads(created.data["labels"]) == {}
    assert result is created


def test_reconcile_patches_statefulset_service_and_configmap():
    """Labels are patched onto the StatefulSet template, Service, and ConfigMap."""
    client = MagicMock()
    cm = MagicMock()
    cm.data = {"labels": "{}"}
    client.get.return_value = cm

    reconcile_charm_labels(
        client=client,
        app_name="myapp",
        namespace="ns",
        label_configmap_name="labels-cm",
        labels={"mesh.io/tier": "backend"},
    )

    patch_calls = client.patch.call_args_list
    assert len(patch_calls) == 3
    assert patch_calls[0].kwargs["res"] == StatefulSet
    assert patch_calls[1].kwargs["res"] == Service
    assert patch_calls[2].kwargs["res"] == ConfigMap


def test_reconcile_removes_previously_set_labels():
    """Labels in the configmap but not in the new set are patched as None (removal)."""
    client = MagicMock()
    cm = MagicMock()
    cm.data = {"labels": json.dumps({"old-label": "old-val"})}
    client.get.return_value = cm

    reconcile_charm_labels(
        client=client,
        app_name="myapp",
        namespace="ns",
        label_configmap_name="labels-cm",
        labels={"new-label": "new-val"},
    )

    sts_patch = client.patch.call_args_list[0].kwargs["obj"]
    patch_labels = sts_patch["spec"]["template"]["metadata"]["labels"]
    assert patch_labels["old-label"] is None
    assert patch_labels["new-label"] == "new-val"


def test_reconcile_creates_configmap_on_404():
    """If the configmap doesn't exist, it's created automatically."""
    client = MagicMock()
    client.get.side_effect = _make_http_status_error(404)

    reconcile_charm_labels(
        client=client,
        app_name="myapp",
        namespace="ns",
        label_configmap_name="labels-cm",
        labels={"x": "y"},
    )

    client.create.assert_called_once()
    assert client.patch.call_count == 3


def test_reconcile_reraises_non_404_http_errors():
    client = MagicMock()
    client.get.side_effect = _make_http_status_error(500)

    with pytest.raises(httpx.HTTPStatusError):
        reconcile_charm_labels(
            client=client,
            app_name="myapp",
            namespace="ns",
            label_configmap_name="labels-cm",
            labels={"x": "y"},
        )


def test_reconcile_updates_configmap_with_current_labels_only():
    """After reconciliation, the configmap stores only the current labels."""
    client = MagicMock()
    cm = MagicMock()
    cm.data = {"labels": json.dumps({"removed": "val", "kept": "val"})}
    client.get.return_value = cm

    reconcile_charm_labels(
        client=client,
        app_name="myapp",
        namespace="ns",
        label_configmap_name="labels-cm",
        labels={"kept": "val", "added": "new"},
    )

    assert json.loads(cm.data["labels"]) == {"kept": "val", "added": "new"}
