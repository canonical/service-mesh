#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests ensuring every provides/requires relation is exercised except for tracing.

Provides:
  * provide-cmr-mesh  -> covered HERE (test_provide_cmr_mesh_relation_settles)
  * service-mesh      -> covered HERE (test_service_mesh_relation_settles)
  * metrics-endpoint  -> covered HERE (test_metrics_endpoint_relation_settles)

Requires:
  * charm-tracing     -> intentionally skipped
"""

import logging

import pytest
from helpers import (
    APP_NAME,
    istio_k8s,
)
from jubilant import Juju, all_active, all_agents_idle

logger = logging.getLogger(__name__)

BOOKINFO_DETAILS = "bookinfo-details-k8s"
PROMETHEUS = "prometheus-k8s"
CMR_MODEL_SUFFIX = "cmr"


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_dependencies(istio_juju: Juju):
    """Deploy istio-k8s in istio-system model."""
    status = istio_juju.status()
    assert istio_k8s.application_name in status.apps
    assert status.apps[istio_k8s.application_name].is_active


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_beacon(juju: Juju, istio_beacon_charm, istio_beacon_resources):
    """Deploy istio-beacon-k8s charm."""
    juju.deploy(
        istio_beacon_charm,
        app=APP_NAME,
        resources=istio_beacon_resources,
        trust=True,
    )
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME) and all_active(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
def test_service_mesh_relation_settles(juju: Juju):
    """Relate beacon's service-mesh (provides service_mesh) to a real requirer and verify settle."""
    juju.deploy(
        BOOKINFO_DETAILS,
        app=BOOKINFO_DETAILS,
        channel="latest/stable",
        trust=True,
    )
    juju.integrate(f"{BOOKINFO_DETAILS}:service-mesh", APP_NAME)
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME, BOOKINFO_DETAILS)
        and all_active(s, APP_NAME, BOOKINFO_DETAILS),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
def test_metrics_endpoint_relation_settles(juju: Juju):
    """Relate beacon's metrics-endpoint (provides prometheus_scrape) to prometheus-k8s and verify settle."""
    juju.deploy(
        PROMETHEUS,
        app=PROMETHEUS,
        channel="3.11/edge",
        trust=True,
    )
    juju.integrate(f"{PROMETHEUS}:metrics-endpoint", f"{APP_NAME}:metrics-endpoint")
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME, PROMETHEUS)
        and all_active(s, APP_NAME, PROMETHEUS),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
def test_provide_cmr_mesh_relation_settles(juju: Juju, temp_model_factory):
    """Relate beacon's provide-cmr-mesh (provides cross_model_mesh) cross-model to a real requirer and verify settle."""
    cmr_model = temp_model_factory.get_juju(CMR_MODEL_SUFFIX)
    cmr_model.deploy(
        BOOKINFO_DETAILS,
        app=BOOKINFO_DETAILS,
        channel="latest/stable",
        trust=True,
    )
    # Beacon (provider) offers its provide-cmr-mesh endpoint cross-model.
    juju.cli("offer", f"{juju.model}.{APP_NAME}:provide-cmr-mesh", include_model=False)
    cmr_model.cli("consume", f"admin/{juju.model}.{APP_NAME}")
    cmr_model.integrate(f"{BOOKINFO_DETAILS}:require-cmr-mesh", APP_NAME)
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME) and all_active(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )
    cmr_model.wait(
        lambda s: all_agents_idle(s, BOOKINFO_DETAILS) and all_active(s, BOOKINFO_DETAILS),
        timeout=1000,
        delay=5,
        successes=3,
    )
