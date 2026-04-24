# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for PolicyResourceManager."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from lightkube.models.meta_v1 import ObjectMeta

from canonical_service_mesh.enums import MeshType
from canonical_service_mesh.k8s.resource_manager._resource_manager import (
    PolicyResourceManager,
)
from canonical_service_mesh.k8s.types.istio import AuthorizationPolicy
from canonical_service_mesh.models.istio import AuthorizationPolicySpec


def _make_charm():
    charm = MagicMock()
    charm.app.name = "test-app"
    charm.model.name = "test-model"
    return charm


def _make_auth_policy(name="test-policy"):
    return AuthorizationPolicy(
        metadata=ObjectMeta(name=name, namespace="test-model"),
        spec=AuthorizationPolicySpec(),
    )


def test_prm_get_builder_raises_for_unknown_mesh():
    with pytest.raises(ValueError, match="unknown mesh type"):
        PolicyResourceManager._get_policy_resource_builder("not-a-mesh")


@patch.object(PolicyResourceManager, "_build_policy_resources", return_value=[])
def test_prm_reconcile_empty_calls_delete(mock_build):
    """No resources produced → reconcile deletes everything."""
    prm = PolicyResourceManager(charm=_make_charm(), lightkube_client=MagicMock())
    prm.delete = MagicMock()
    prm.reconcile(policies=[], mesh_type=MeshType.istio)
    prm.delete.assert_called_once()


@patch.object(PolicyResourceManager, "_build_policy_resources")
def test_prm_reconcile_delegates_to_krm(mock_build):
    mock_build.return_value = [_make_auth_policy()]
    prm = PolicyResourceManager(charm=_make_charm(), lightkube_client=MagicMock())
    prm._krm = MagicMock()
    prm.reconcile(policies=["p"], mesh_type=MeshType.istio)
    prm._krm.reconcile.assert_called_once()


@patch.object(PolicyResourceManager, "_build_policy_resources")
def test_prm_reconcile_merges_raw_policies(mock_build):
    """raw_policies are appended to built policies before reconciliation."""
    mock_build.return_value = [_make_auth_policy("built")]
    prm = PolicyResourceManager(charm=_make_charm(), lightkube_client=MagicMock())
    prm._krm = MagicMock()

    prm.reconcile(
        policies=["p"], mesh_type=MeshType.istio, raw_policies=[_make_auth_policy("raw")]
    )
    reconciled = prm._krm.reconcile.call_args.args[0]
    assert len(reconciled) == 2


def test_prm_validate_rejects_unsupported_type():
    prm = PolicyResourceManager(charm=_make_charm(), lightkube_client=MagicMock())
    with pytest.raises(TypeError, match="not a supported policy resource type"):
        prm._validate_raw_policies(["not-a-policy"])


def test_prm_delete_ignores_404():
    prm = PolicyResourceManager(charm=_make_charm(), lightkube_client=MagicMock())
    response = MagicMock(spec=httpx.Response)
    response.status_code = 404
    prm._krm = MagicMock()
    prm._krm.delete.side_effect = httpx.HTTPStatusError(
        message="Not Found", request=MagicMock(), response=response
    )
    prm.delete(ignore_missing=True)  # should not raise


def test_prm_delete_reraises_non_404():
    prm = PolicyResourceManager(charm=_make_charm(), lightkube_client=MagicMock())
    response = MagicMock(spec=httpx.Response)
    response.status_code = 500
    prm._krm = MagicMock()
    prm._krm.delete.side_effect = httpx.HTTPStatusError(
        message="Server Error", request=MagicMock(), response=response
    )
    with pytest.raises(httpx.HTTPStatusError):
        prm.delete(ignore_missing=True)
