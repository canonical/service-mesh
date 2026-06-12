# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from conftest import get_unit_info
from helpers import istio_k8s
from jubilant import Juju, all_active

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
TESTER_HTTP = "tester-http"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy_istio")
def test_deploy_istio(juju: Juju):
    """Deploy istio-k8s."""
    juju.deploy(**asdict(istio_k8s))
    juju.wait(lambda s: all_active(s, istio_k8s.app), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_deploy_istio_ingress", depends=["test_deploy_istio"])
def test_deploy_istio_ingress(juju: Juju, istio_ingress_charm, resources):
    """Deploy istio-ingress-k8s."""
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_deploy_tester_http", depends=["test_deploy_istio_ingress"])
def test_deploy_tester_http(juju: Juju, tester_http_charm):
    """Deploy tester-http."""
    juju.deploy(
        tester_http_charm,
        app=TESTER_HTTP,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.wait(lambda s: all_active(s, TESTER_HTTP), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_relate_gateway_metadata", depends=["test_deploy_tester_http"])
def test_relate_gateway_metadata(juju: Juju):
    """Relate tester-http to istio-ingress-k8s via gateway-metadata."""
    juju.integrate(f"{TESTER_HTTP}:gateway-metadata", f"{APP_NAME}:gateway-metadata")
    juju.wait(lambda s: all_active(s, APP_NAME, TESTER_HTTP), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_gateway_metadata", depends=["test_relate_gateway_metadata"])
def test_gateway_metadata_content(juju: Juju):
    """Validate that gateway metadata is correctly published."""
    # Get the relation data from the requirer side (tester-http)
    # Note: We query from the requirer side because juju show-unit doesn't show
    # the provider's own application-data when querying the provider unit
    unit_info = get_unit_info(f"{TESTER_HTTP}/0", juju.model)

    # Find the gateway-metadata relation
    relations = unit_info["relation-info"]
    gateway_metadata_relation = next(
        (r for r in relations if r["endpoint"] == "gateway-metadata"), None
    )
    assert gateway_metadata_relation is not None, "gateway-metadata relation not found"

    # Get the application data (where the provider publishes metadata)
    app_data = gateway_metadata_relation.get("application-data", {})
    assert "metadata" in app_data, "metadata key not found in relation databag"

    # Parse and validate the metadata
    metadata = json.loads(app_data["metadata"])

    # Expected values based on charm implementation
    # managed_name = f"{app_name}-istio" (from charm.py:161)
    expected_deployment = f"{APP_NAME}-istio"
    expected_service_account = f"{APP_NAME}-istio"

    # Validate metadata fields
    assert metadata["namespace"] == juju.model, (
        f"Expected namespace {juju.model}, got {metadata['namespace']}"
    )
    assert metadata["gateway_name"] == APP_NAME, (
        f"Expected gateway_name {APP_NAME}, got {metadata['gateway_name']}"
    )
    assert metadata["deployment_name"] == expected_deployment, (
        f"Expected deployment_name {expected_deployment}, got {metadata['deployment_name']}"
    )
    assert metadata["service_account"] == expected_service_account, (
        f"Expected service_account {expected_service_account}, got {metadata['service_account']}"
    )
    logger.info(f"Gateway metadata validated successfully: {metadata}")
