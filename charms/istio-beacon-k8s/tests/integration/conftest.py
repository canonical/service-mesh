#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from helpers import istio_k8s
from jubilant import all_active, all_agents_idle

logger = logging.getLogger(__name__)

CHARM_DIR = Path(__file__).parents[2]  # The istio-beacon-k8s charm root.
TESTER_DIR = Path(__file__).parent / "testers" / "service-mesh-tester"


def _pack(charm_dir: Path) -> Path:
    """Pack the charm in ``charm_dir`` and return the resulting ``.charm`` path."""
    logger.info("Packing charm in %s", charm_dir)
    subprocess.run(["charmcraft", "pack"], cwd=charm_dir, check=True)
    charms = list(charm_dir.glob("*.charm"))
    assert charms, f"No charm was packed in {charm_dir}"
    assert len(charms) == 1, f"Found more than one charm {charms}"
    return charms[0].resolve()


def _get_resources(charm_dir: Path) -> dict:
    """Extract oci-image resources from ``charmcraft.yaml`` in ``charm_dir``."""
    charmcraft_yaml = yaml.safe_load((charm_dir / "charmcraft.yaml").read_text())
    resources = charmcraft_yaml.get("resources", {})
    return {
        name: spec["upstream-source"]
        for name, spec in resources.items()
        if spec.get("type") == "oci-image"
    }


@pytest.fixture(scope="session")
def istio_beacon_charm():
    """Build istio-beacon charm once per session."""
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)
    return _pack(CHARM_DIR)


@pytest.fixture(scope="session")
def istio_beacon_resources():
    """Extract resources from charmcraft.yaml."""
    return _get_resources(CHARM_DIR)


@pytest.fixture(scope="session")
def service_mesh_tester():
    """Build service-mesh-tester charm once per session."""
    return _pack(TESTER_DIR)


@pytest.fixture(scope="session")
def tester_resources():
    """Extract tester charm resources."""
    return _get_resources(TESTER_DIR)


@pytest.fixture(scope="module")
def istio_juju(temp_model_factory):
    """Deploy istio-k8s in istio-system model."""
    # Use temp_model_factory to create model - automatically respects --keep-models
    istio_juju_model = temp_model_factory.get_juju("istio-system")

    # Deploy istio-k8s
    istio_juju_model.deploy(
        charm=istio_k8s.entity_url,
        app=istio_k8s.application_name,
        channel=istio_k8s.channel,
        trust=istio_k8s.trust,
        config=istio_k8s.config,
    )

    # Wait for istio-k8s to be active
    istio_juju_model.wait(
        lambda s: all_agents_idle(s, istio_k8s.application_name) and all_active(s, istio_k8s.application_name),
        timeout=1000,
        delay=5,
        successes=3,
    )

    return istio_juju_model
