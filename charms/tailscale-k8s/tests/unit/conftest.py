#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from lightkube import ApiError
from scenario import Container, Context, Secret

from charm import TailscaleK8sCharm


def _make_api_error(code: int = 404):
    """Create a lightkube ApiError with the given status code."""
    mock_error = ApiError(
        response=MagicMock(status_code=code, json=MagicMock(return_value={"code": code}))
    )
    mock_error.status = MagicMock(code=code)
    return mock_error


@pytest.fixture()
def tailscale_context():
    """Create a scenario Context with K8s API calls mocked to return 404 (no existing operator)."""
    with patch("charm.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get.side_effect = _make_api_error(404)
        # KubernetesResourceManager.get_deployed_resources() lists by label; an
        # empty list means "nothing deployed yet" so reconcile just applies.
        mock_client.list.return_value = []
        yield Context(charm_type=TailscaleK8sCharm)


@pytest.fixture()
def operator_container():
    """Create a tailscale-operator container that can connect."""
    return Container(
        name="tailscale-operator",
        can_connect=True,
    )


@pytest.fixture()
def operator_container_not_ready():
    """Create a tailscale-operator container that cannot connect."""
    return Container(
        name="tailscale-operator",
        can_connect=False,
    )


@pytest.fixture()
def credentials_secret():
    """Create a Juju secret with OAuth credentials."""
    return Secret(
        tracked_content={"client-id": "test-client-id", "client-secret": "test-client-secret"},
        latest_content={"client-id": "test-client-id", "client-secret": "test-client-secret"},
        owner="app",
    )
