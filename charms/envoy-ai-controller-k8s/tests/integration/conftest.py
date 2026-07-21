# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for the envoy-ai-controller-k8s integration suite; steps live in ``steps/``."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_jubilant import get_resources, pack

pytest_plugins = [
    "tests.integration.steps.common_steps",
    "tests.integration.steps.certificates_steps",
    "tests.integration.steps.extension_server_steps",
    "tests.integration.steps.crds_steps",
    "tests.integration.steps.webhook_steps",
    "tests.integration.steps.controllers_steps",
    "tests.integration.steps.scaling_steps",
    "tests.integration.steps.extproc_injection_steps",
    "tests.integration.steps.otlp_steps",
    "tests.integration.steps.grafana_steps",
    "tests.integration.steps.metrics_endpoint_steps",
]


@pytest.fixture(scope="session")
def charm() -> Path:
    """The packed AI controller charm; from CHARM_PATH in CI, else packed locally."""
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
