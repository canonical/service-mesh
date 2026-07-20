#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
import scenario

from charm import IstioBeaconCharm


@pytest.fixture(autouse=True)
def mock_charm_lightkube_client(request):
    """Global mock for the Charm's Lightkube Client to avoid loading kubeconfig in CI."""
    # Skip this fixture if the test has explicitly disabled it.
    # To use this feature in a test, mark it with @pytest.mark.disable_charm_lightkube_client_autouse
    if "disable_charm_lightkube_client_autouse" in request.keywords:
        yield
    else:
        with patch("charm.Client") as mocked_lightkube_client:
            yield mocked_lightkube_client


@pytest.fixture(autouse=True)
def mock_lib_lightkube_client(request):
    """Global mock for the service mesh library's Lightkube Client to avoid loading kubeconfig in CI."""
    # Skip this fixture if the test has explicitly disabled it.
    # To use this feature in a test, mark it with @pytest.mark.disable_service_lightkube_client_autouse
    if "disable_service_lightkube_client_autouse" in request.keywords:
        yield
    else:
        # patch Client usage in service_mesh library
        with patch("lightkube.Client") as mocked_lightkube_client:
            yield mocked_lightkube_client


@pytest.fixture()
def istio_beacon_charm():
    yield IstioBeaconCharm


@pytest.fixture()
def istio_beacon_context(istio_beacon_charm):
    yield scenario.Context(charm_type=istio_beacon_charm)
