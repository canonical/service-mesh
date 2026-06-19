# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from canonical_service_mesh.k8s.resource_manager import PolicyResourceManager
from canonical_service_mesh.k8s.types.istio import AuthorizationPolicy
from charmlibs.interfaces.service_mesh import MeshType
from lightkube.models.meta_v1 import ObjectMeta
from ops import CharmBase


@pytest.fixture
def mock_charm():
    charm = MagicMock(spec=CharmBase)
    charm.app.name = "test-app"
    charm.model.name = "test-model"
    return charm


@pytest.fixture
def mock_lightkube_client():
    return MagicMock()


def test_policy_resource_manager_reconcile_empty_policies_calls_delete(mock_charm, mock_lightkube_client):
    """Test reconcile calls delete when policies list is empty."""
    with patch('canonical_service_mesh.k8s.resource_manager._resource_manager.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
        )

        # Mock the _krm
        prm._krm = MagicMock()
        # Call reconcile with empty policies
        prm.reconcile([], MeshType.istio)
        # Should call delete instead of trying to build policies
        prm._krm.delete.assert_called_once()


def test_policy_resource_manager_delete_handles_404_error(mock_charm, mock_lightkube_client):
    """Test delete method handles 404 errors gracefully when ignore_missing=True."""
    with patch('canonical_service_mesh.k8s.resource_manager._resource_manager.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
        )

        # Mock the _krm and logger
        prm._krm = MagicMock()
        prm.log = MagicMock()

        # Mock a 404 HTTP error
        mock_response = Mock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError("Not found", request=Mock(), response=mock_response)
        prm._krm.delete.side_effect = http_error

        # Should not raise an exception
        prm.delete(ignore_missing=True)

        prm.log.info.assert_called_once_with("CRD not found, skipping deletion")


def test_policy_resource_manager_reconcile_with_raw_policies_does_not_delete(mock_charm, mock_lightkube_client):
    """Test reconcile with empty policies but raw_policies provided does NOT call delete."""
    with patch('canonical_service_mesh.k8s.resource_manager._resource_manager.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
        )

        prm._krm = MagicMock()

        # Create a raw AuthorizationPolicy
        raw_policy = AuthorizationPolicy(
            metadata=ObjectMeta(name="test-policy", namespace="test-ns"),
            spec={"rules": []},
        )

        # Call reconcile with empty policies but with raw_policies
        prm.reconcile([], MeshType.istio, raw_policies=[raw_policy])

        # Should NOT call delete - should call reconcile instead
        prm._krm.delete.assert_not_called()
        prm._krm.reconcile.assert_called_once()
        # Verify raw_policy was passed to krm.reconcile
        reconciled_resources = prm._krm.reconcile.call_args[0][0]
        assert len(reconciled_resources) == 1
        assert reconciled_resources[0].metadata.name == "test-policy"


def test_policy_resource_manager_validate_raw_policies_rejects_unsupported_type(mock_charm, mock_lightkube_client):
    """Test that raw_policies with unsupported type raises TypeError."""
    with patch('canonical_service_mesh.k8s.resource_manager._resource_manager.KubernetesResourceManager'):
        prm = PolicyResourceManager(
            charm=mock_charm,
            lightkube_client=mock_lightkube_client,
        )

        prm._krm = MagicMock()
        prm.log = MagicMock()

        # Create an object of wrong type (not AuthorizationPolicy)
        wrong_type_policy = MagicMock()
        wrong_type_policy.__class__.__name__ = "WrongType"

        # Should raise TypeError
        with pytest.raises(TypeError, match="not a supported policy resource type"):
            prm.reconcile([], MeshType.istio, raw_policies=[wrong_type_policy])
