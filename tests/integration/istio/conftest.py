"""Pytest configuration for Service Mesh integration tests."""

from typing import Dict

import pytest


def pytest_bdd_apply_tag(tag, function):
    """Map Gherkin tags to pytest markers."""
    if tag.startswith("xfail"):
        reason = tag.split(":", 1)[1].strip() if ":" in tag else ""
        marker = pytest.mark.xfail(reason=reason)
        marker(function)
        return True
    return None


# Register step definition modules as pytest plugins
pytest_plugins = [
    "tests.integration.istio.steps.common_steps",
    "tests.integration.istio.steps.istio_integration_steps",
    "tests.integration.istio.steps.authorization_policies_steps",
    "tests.integration.istio.steps.managed_mode_steps",
    "tests.integration.istio.steps.hardened_mode_steps",
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


@pytest.fixture(scope="module")
def ingress_info() -> Dict:
    """Store the ingress app name for the test module."""
    return {"app_name": None}


@pytest.fixture(scope="function")
def istio_config() -> Dict:
    """Accumulate config options for istio-k8s within a scenario."""
    return {}


@pytest.fixture(scope="function")
def beacon_config() -> Dict:
    """Accumulate config options for istio-beacon-k8s within a scenario."""
    return {}


@pytest.fixture(scope="function")
def ingress_config() -> Dict:
    """Accumulate config options for istio-ingress-k8s within a scenario."""
    return {}
