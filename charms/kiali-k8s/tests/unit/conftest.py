#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.tempo_api import TempoApiRequirer
from scenario import Context

from charm import KialiCharm as ThisCharm


@pytest.fixture(autouse=True)
def mock_requests_get(request):
    """Mock requests.get to return a 200 status code so it looks like Kiali is available in the collect_status hook.

    To disable this fixture in a specific test, mark it with @pytest.marl.disable_requests_get_autouse.
    """
    if "disable_requests_get_autouse" in request.keywords:
        yield
    else:
        with patch("charm.requests.get") as mock_requests_get:
            mock_requests_get.return_value.status_code = 200
            yield mock_requests_get


@pytest.fixture(scope="function")
def this_charm():
    with patch.object(TempoApiRequirer, "_validate_relation_metadata", return_value=None):
        # This validation step always fails in CI because it checks a metadata.yaml and we don't have one.
        yield ThisCharm


@pytest.fixture(scope="function")
def this_charm_context(this_charm):
    yield Context(charm_type=this_charm)
