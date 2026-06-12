#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock, patch

import pytest
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Namespace
from ops.testing import Harness

from charm import IstioBeaconCharm


@pytest.fixture()
def harness():
    harness = Harness(IstioBeaconCharm)
    harness.set_model_name("istio-system")
    yield harness
    harness.cleanup()


@pytest.mark.parametrize(
    "labels_before, patched, labels_after",
    [
        (
            # Assert that, when there are no waypoint labels, the expected labels are added
            {},
            True,
            {
                "istio.io/use-waypoint": "istio-system-istio-beacon-k8s-waypoint",
                "istio.io/dataplane-mode": "ambient",
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-system.istio-beacon-k8s",
            },
        ),
        (
            # Assert that existing labels get preserved on positive cases
            {"foo": "bar"},
            True,
            {
                "istio.io/use-waypoint": "istio-system-istio-beacon-k8s-waypoint",
                "istio.io/dataplane-mode": "ambient",
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-system.istio-beacon-k8s",
                "foo": "bar",
            },
        ),
        (
            # Assert that, when we already manage the labels, they get updated
            {
                "istio.io/use-waypoint": "istio-system-istio-beacon-k8s-waypoint",
                # "istio.io/dataplane-mode": "ambient",  # omitted for this case on purpose
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-system.istio-beacon-k8s",
                "foo": "bar",
            },
            True,
            {
                "istio.io/use-waypoint": "istio-system-istio-beacon-k8s-waypoint",
                "istio.io/dataplane-mode": "ambient",
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-system.istio-beacon-k8s",
                "foo": "bar",
            },
        ),
        # Assert that, when we we do not manage the labels, they do not get updated
        (
            {
                "istio.io/use-waypoint": "istio-system-istio-beacon-k8s-waypoint",
                "istio.io/dataplane-mode": "ambient",  # omitted for this case on purpose
                "foo": "bar",
            },
            False,
            "unused arg",
        ),
    ],
)
def test_add_labels(harness: Harness[IstioBeaconCharm], labels_before, patched, labels_after):
    """Test the _add_labels method with namespace labeling logic."""
    harness.begin()
    charm = harness.charm

    mock_namespace = Namespace(
        metadata=ObjectMeta(
            name="istio-system",
            labels=labels_before,
        )
    )

    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        charm._add_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        assert mock_namespace.metadata
        if patched:
            mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
            assert mock_namespace.metadata.labels == labels_after
        else:
            mock_patch.assert_not_called()
            assert mock_namespace.metadata.labels == labels_before


@pytest.mark.parametrize(
    "labels_before, patched, labels_after",
    [
        (
            # Scenario 1: Namespace labels are managed by this charm
            {
                "istio.io/use-waypoint": "istio-system-istio-beacon-k8s-waypoint",
                "istio.io/dataplane-mode": "ambient",
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-system.istio-beacon-k8s",
                "foo": "bar",
            },
            True,
            {
                "foo": "bar",
                "istio.io/use-waypoint": None,
                "istio.io/dataplane-mode": None,
                "charms.canonical.com/istio.io.waypoint.managed-by": None,
            },
        ),
        (
            # Scenario 2: Namespace labels are managed by another entity
            {
                "istio.io/use-waypoint": "another-entity",
                "istio.io/dataplane-mode": "ambient",
                "foo": "bar",
            },
            False,
            {
                "istio.io/use-waypoint": "another-entity",
                "istio.io.dataplane-mode": "ambient",
                "foo": "bar",
            },
        ),
        (
            # Scenario 3: Namespace labels are partially managed by this charm
            {
                "charms.canonical.com/istio.io.waypoint.managed-by": "istio-system.istio-beacon-k8s",
                "foo": "bar",
            },
            True,
            {
                "foo": "bar",
                "istio.io/use-waypoint": None,
                "istio.io/dataplane-mode": None,
                "charms.canonical.com/istio.io.waypoint.managed-by": None,
            },
        ),
        (
            # Scenario 4: Namespace has no labels configured at all
            {},
            False,
            {},
        ),
    ],
)
def test_remove_labels(harness: Harness[IstioBeaconCharm], labels_before, patched, labels_after):
    """Test the _remove_labels method with namespace labeling logic."""
    harness.begin()
    charm = harness.charm

    mock_namespace = Namespace(
        metadata=ObjectMeta(
            name="istio-system",
            labels=labels_before,
        )
    )

    with patch.object(
        charm.lightkube_client, "get", return_value=mock_namespace
    ) as mock_get, patch.object(charm.lightkube_client, "patch") as mock_patch:
        charm._remove_labels()
        mock_get.assert_called_once_with(Namespace, "istio-system")
        assert mock_namespace.metadata
        if patched:
            mock_patch.assert_called_once_with(Namespace, "istio-system", mock_namespace)
            assert mock_namespace.metadata.labels == labels_after
        else:
            mock_patch.assert_not_called()
            assert mock_namespace.metadata.labels == labels_before


def test_sync_waypoint_resources_add_labels(harness: Harness[IstioBeaconCharm]):
    """Test _sync_waypoint_resources when model-on-mesh is True."""
    harness.begin()
    harness.update_config({"model-on-mesh": True})
    charm = harness.charm

    with patch.object(charm, "_get_waypoint_resource_manager") as mock_krm, patch.object(
        charm, "_construct_waypoint"
    ) as mock_construct_waypoint, patch.object(
        charm, "_add_labels"
    ) as mock_add_labels, patch.object(charm, "_remove_labels") as mock_remove_labels:
        mock_krm.return_value.reconcile = MagicMock()
        mock_construct_waypoint.return_value = MagicMock()

        charm._sync_waypoint_resources()

        # Ensure resource manager and waypoint construction were called
        mock_krm.return_value.reconcile.assert_called_once()
        mock_construct_waypoint.assert_called_once()

        # Ensure add_labels is called since model-on-mesh is True
        mock_add_labels.assert_called_once()

        # Ensure remove_labels is not called
        mock_remove_labels.assert_not_called()


def test_sync_waypoint_resources_remove_labels(harness: Harness[IstioBeaconCharm]):
    """Test _sync_waypoint_resources when model-on-mesh is False."""
    harness.begin()
    harness.update_config({"model-on-mesh": False})
    charm = harness.charm

    with patch.object(charm, "_get_waypoint_resource_manager") as mock_krm, patch.object(
        charm, "_construct_waypoint"
    ) as mock_construct_waypoint, patch.object(
        charm, "_add_labels"
    ) as mock_add_labels, patch.object(charm, "_remove_labels") as mock_remove_labels:
        mock_krm.return_value.reconcile = MagicMock()
        mock_construct_waypoint.return_value = MagicMock()

        charm._sync_waypoint_resources()

        # Ensure resource manager and waypoint construction were called
        mock_krm.return_value.reconcile.assert_called_once()
        mock_construct_waypoint.assert_called_once()

        # Ensure remove_labels is called since model-on-mesh is False
        mock_remove_labels.assert_called_once()

        # Ensure add_labels is not called
        mock_add_labels.assert_not_called()


@pytest.mark.parametrize(
    "model_name",
    (
        "some-model",
        "some-really-long-model-name-that-exceeds-63-characters-1234567890"
    )
)
def test_valid_telemetry_labels(model_name, harness: Harness[IstioBeaconCharm]):
    """Test that telemetry labels are valid.

    Presently, this only asserts that the keys and values are <=63 characters.
    """
    harness.set_model_name(model_name)
    harness.begin()
    charm = harness.charm

    # Check that telemetry labels are valid
    for k, v in charm._telemetry_labels.items():
        assert len(k) <= 63
        assert len(v) <= 63
