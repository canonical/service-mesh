"""Pytest configuration for Service Mesh integration tests."""

from typing import Dict

import pytest

# Register step definition modules as pytest plugins
pytest_plugins = [
    "tests.integration.istio.steps.common_steps",
    "tests.integration.istio.steps.istio_integration_steps",
    "tests.integration.istio.steps.authorization_policies_steps",
    "tests.integration.istio.steps.managed_mode_steps",
]


# -------------- Fixtures --------------


@pytest.fixture(scope="module")
def istio_system_juju(temp_model_factory):
    """Create a temporary Juju model for istio-system deployment."""
    yield temp_model_factory.get_juju(suffix="istio-system")


@pytest.fixture
def juju_run_output() -> Dict:
    """Store the output from juju run actions."""
    return {}


@pytest.fixture(scope="module")
def beacon_info() -> Dict:
    """Store the beacon app name and endpoint for the test module."""
    return {"app_name": None, "endpoint": None}
