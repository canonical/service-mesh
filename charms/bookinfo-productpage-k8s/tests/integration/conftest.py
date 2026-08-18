"""Fixtures for productpage charm integration tests."""

import pytest
from pytest_jubilant import get_resources, pack


@pytest.fixture(scope="module")
def charm():
    """Build and package the productpage charm."""
    return pack(".")


@pytest.fixture(scope="module")
def resources():
    """Get resources for productpage charm."""
    return get_resources(".")
