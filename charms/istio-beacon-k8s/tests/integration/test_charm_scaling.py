#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time

import pytest
from canonical_service_mesh.utils import charm_kubernetes_label
from helpers import (
    APP_NAME,
    get_hpa,
    istio_k8s,
    scale_application,
)
from jubilant import Juju, all_active, all_agents_idle

logger = logging.getLogger(__name__)

TESTER_APP_NAME = "tester"


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_dependencies(istio_juju: Juju):
    """Deploy istio-k8s in istio-system model."""
    # The istio_juju fixture handles deployment, this test just ensures it runs
    # and validates istio-k8s is active
    status = istio_juju.status()
    assert istio_k8s.application_name in status.apps
    assert status.apps[istio_k8s.application_name].is_active


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deployment(juju: Juju, istio_beacon_charm, istio_beacon_resources):
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


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_service_mesh_relation(juju: Juju, service_mesh_tester):
    """Adds a tester charm and creates a service mesh relation between beacon and the tester charm.

    The subsequent scaling test makes sure that the scaling up/down happens successfully with the service mesh relation in place.
    """
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    juju.deploy(
        service_mesh_tester,
        app=TESTER_APP_NAME,
        resources=resources,
        trust=True,
    )
    juju.wait(
        lambda s: all_agents_idle(s, TESTER_APP_NAME) and all_active(s, TESTER_APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )
    juju.integrate("tester:service-mesh", APP_NAME)
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME, TESTER_APP_NAME) and all_active(s, APP_NAME, TESTER_APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize(
    "n_units",
    (
        # Scale up from 1 to 3
        3,
        # Scale down to 2
        2,
    ),
)
def test_waypoint_scaling(juju: Juju, n_units):
    """Tests that, when the application is scaled, the HPA managing replicas on the Waypoint is scaled too.

    This test also makes sure that the scaling does not affect any existing service mesh relation.
    Note: This test is stateful and will leave the deployment at a scale of 2.
    """
    model_name = juju.model
    assert model_name is not None

    # Scale the application
    scale_application(juju, APP_NAME, n_units)

    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME) and all_active(s, APP_NAME),
        timeout=2000,
        delay=5,
        successes=3,
    )

    waypoint_name = charm_kubernetes_label(
        model_name=model_name,
        app_name=APP_NAME,
        suffix="-waypoint",
        separator="-",
        max_length=63
    )
    waypoint_hpa = get_hpa(model_name, waypoint_name)
    assert waypoint_hpa is not None
    assert waypoint_hpa.spec.minReplicas == n_units  # pyright: ignore[reportOptionalMemberAccess]
    assert waypoint_hpa.spec.maxReplicas == n_units  # pyright: ignore[reportOptionalMemberAccess]

    assert wait_for_hpa_current_replicas(
        model_name, waypoint_name, n_units
    ), f"Expected currentReplicas to be {n_units}, got {waypoint_hpa.status.currentReplicas}"  # pyright: ignore[reportOptionalMemberAccess]


def wait_for_hpa_current_replicas(
    namespace, hpa_name, expected_replicas, retries=10, delay=10
):
    """Wait for HPA current replicas to match expected count.

    Args:
        namespace: Kubernetes namespace (model name).
        hpa_name: Name of the HPA resource.
        expected_replicas: Expected number of replicas.
        retries: Number of retries.
        delay: Delay in seconds between retries.

    Returns:
        True if replicas match, False otherwise.
    """
    for _ in range(retries):
        # freshly grab the hpa, but no need to assert its existence as that should be checked by the caller of this method
        waypoint_hpa = get_hpa(namespace, hpa_name)
        if waypoint_hpa and waypoint_hpa.status.currentReplicas == expected_replicas:  # pyright: ignore[reportOptionalMemberAccess]
            return True
        time.sleep(delay)
    return False
