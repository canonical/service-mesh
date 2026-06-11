# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
import time
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from helpers import get_hpa, istio_k8s
from jubilant import Juju, all_active

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy_dependencies")
def test_deploy_dependencies(juju: Juju):
    """Deploy istio as a dependency."""
    juju.deploy(**asdict(istio_k8s))
    juju.wait(lambda s: all_active(s, istio_k8s.app), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_deployment", depends=["test_deploy_dependencies"])
def test_deployment(juju: Juju, istio_ingress_charm, resources):
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@pytest.mark.parametrize(
    "n_units",
    (
        3,  # Scale up from 1 to 3
        2,  # Scale down to 2
    ),
)
@pytest.mark.dependency(name="test_gateway_scaling", depends=["test_deployment"])
def test_gateway_scaling(juju: Juju, n_units):
    """Tests that, when the application is scaled, the HPA managing replicas on the Gateway is scaled too.

    Note: This test is stateful and will leave the deployment at a scale of 2.
    """
    status = juju.status()
    current_units = len(status.apps[APP_NAME].units)
    if n_units > current_units:
        juju.add_unit(APP_NAME, num_units=n_units - current_units)
    elif n_units < current_units:
        juju.remove_unit(APP_NAME, num_units=current_units - n_units)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)

    hpa = get_hpa(juju.model, APP_NAME)

    assert hpa is not None
    assert hpa.spec.minReplicas == n_units
    assert hpa.spec.maxReplicas == n_units

    assert wait_for_hpa_current_replicas(juju.model, APP_NAME, n_units), (
        f"Expected currentReplicas to be {n_units}, got {hpa.status.currentReplicas}"
    )


def wait_for_hpa_current_replicas(namespace, hpa_name, expected_replicas, retries=10, delay=10):
    for _ in range(retries):
        hpa = get_hpa(namespace, hpa_name)
        if hpa and hpa.status.currentReplicas == expected_replicas:
            return True
        time.sleep(delay)
    return False
