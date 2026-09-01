#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Integration tests ensuring every provides/requires relation is exercised except for tracing.

Provides:
  * grafana-dashboard   -> covered HERE (test_grafana_dashboard)
  * istio-metadata      -> covered HERE (test_istio_metadata)
  * metrics-endpoint    -> covered HERE (test_metrics_endpoint)

Requires:
  * charm-tracing        -> intentionally skipped
  * workload-tracing     -> intentionally skipped
  * istio-ingress-config -> covered HERE (test_istio_ingress_config)
  * jwks-ca-cert         -> covered HERE (test_jwks_ca_cert)
"""

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
resources = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}

# Real charms used as relation counterparts.
PROMETHEUS = "prometheus-k8s"
GRAFANA = "grafana-k8s"
SELF_SIGNED_CERTIFICATES = "self-signed-certificates"
KIALI = "kiali-k8s"
ISTIO_INGRESS = "istio-ingress-k8s"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, istio_core_charm):
    """Build the charm-under-test and deploy it."""
    assert ops_test.model
    await ops_test.model.deploy(
        istio_core_charm, resources=resources, application_name=APP_NAME, trust=True
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_metrics_endpoint(ops_test: OpsTest):
    """Exercise the `metrics-endpoint` (prometheus_scrape) provides relation with prometheus-k8s."""
    assert ops_test.model
    await ops_test.model.deploy(PROMETHEUS, channel="2/edge", trust=True)
    await ops_test.model.add_relation(f"{APP_NAME}:metrics-endpoint", PROMETHEUS)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, PROMETHEUS], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_grafana_dashboard(ops_test: OpsTest):
    """Exercise the `grafana-dashboard` (grafana_dashboard) provides relation with grafana-k8s."""
    assert ops_test.model
    await ops_test.model.deploy(GRAFANA, channel="2/edge", trust=True)
    await ops_test.model.add_relation(f"{APP_NAME}:grafana-dashboard", GRAFANA)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, GRAFANA], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_jwks_ca_cert(ops_test: OpsTest):
    """Exercise the `jwks-ca-cert` (certificate_transfer) requires relation with self-signed-certificates."""
    assert ops_test.model
    await ops_test.model.deploy(SELF_SIGNED_CERTIFICATES, channel="latest/edge")
    await ops_test.model.add_relation(
        f"{APP_NAME}:jwks-ca-cert", f"{SELF_SIGNED_CERTIFICATES}:send-ca-cert"
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, SELF_SIGNED_CERTIFICATES], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_istio_metadata(ops_test: OpsTest):
    """Exercise the `istio-metadata` (istio_metadata) provides relation with kiali-k8s.

    kiali-k8s requires `prometheus-api` and `istio-metadata` to reach active, so we relate
    it to the already-deployed prometheus-k8s in addition to istio-k8s.
    """
    assert ops_test.model
    await ops_test.model.deploy(KIALI, channel="2/edge", trust=True)
    await ops_test.model.add_relation(f"{KIALI}:prometheus-api", f"{PROMETHEUS}:prometheus-api")
    await ops_test.model.add_relation(f"{KIALI}:istio-metadata", f"{APP_NAME}:istio-metadata")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, PROMETHEUS, KIALI], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_istio_ingress_config(ops_test: OpsTest):
    """Exercise the `istio-ingress-config` (istio_ingress_config) requires relation with istio-ingress-k8s."""
    assert ops_test.model
    await ops_test.model.deploy(
        ISTIO_INGRESS,
        channel="2/edge",
        resources=resources,
        trust=True,
    )
    await ops_test.model.add_relation(
        f"{APP_NAME}:istio-ingress-config", f"{ISTIO_INGRESS}:istio-ingress-config"
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, ISTIO_INGRESS], status="active", timeout=1000
    )
