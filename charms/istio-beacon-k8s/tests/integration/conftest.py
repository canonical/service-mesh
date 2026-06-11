#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import shutil
from pathlib import Path

import pytest
from helpers import istio_k8s
from jubilant import all_active, all_agents_idle
from pytest_jubilant import get_resources, pack


@pytest.fixture(scope="session")
def istio_beacon_charm():
    """Build istio-beacon charm once per session."""
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)

    charm = pack()
    return charm


@pytest.fixture(scope="session")
def istio_beacon_resources():
    """Extract resources from charmcraft.yaml."""
    return get_resources(".")


@pytest.fixture(scope="session")
def service_mesh_tester():
    """Build service-mesh-tester charm once per session."""
    charm_path = Path(__file__).parent / "testers" / "service-mesh-tester"

    # Update libraries in the tester charm from root lib folder
    root_lib_folder = Path(__file__).parent.parent.parent / "lib"
    tester_lib_folder = charm_path / "lib"

    if tester_lib_folder.exists():
        shutil.rmtree(tester_lib_folder)
    shutil.copytree(root_lib_folder, tester_lib_folder)

    charm = pack(str(charm_path))
    return charm


@pytest.fixture(scope="session")
def tester_resources():
    """Extract tester charm resources."""
    return get_resources("./tests/integration/testers/service-mesh-tester")


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
