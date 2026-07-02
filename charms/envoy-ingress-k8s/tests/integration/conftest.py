# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for the envoy-ingress-k8s integration suite; steps live in ``steps/``."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_jubilant import get_resources, pack

pytest_plugins = [
    "tests.integration.steps.common_steps",
    "tests.integration.steps.gateway_resources_steps",
    "tests.integration.steps.ingress_steps",
    "tests.integration.steps.certificates_steps",
]


@pytest.fixture(scope="session")
def charm() -> Path:
    """The packed ingress charm; from CHARM_PATH in CI, else packed locally."""
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)
    return pack()


@pytest.fixture(scope="session")
def resources() -> dict:
    """OCI-image resources resolved from charmcraft.yaml upstream-source."""
    return get_resources() or {}


@pytest.fixture()
def context() -> SimpleNamespace:
    """Per-scenario scratch space for values passed between steps."""
    return SimpleNamespace()
