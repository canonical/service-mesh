#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests that istio-beacon creates AuthorizationPolicies that enable traffic for charms related cross-model."""

import pytest
from helpers import (
    APP_NAME,
    RECEIVER,
    SENDER,
    assert_request_returns_http_code,
    istio_k8s,
)
from jubilant import Juju, all_active, all_agents_idle


@pytest.fixture(scope="module")
def sender_model(temp_model_factory):
    """Create and return a Juju instance for the sender model."""
    sender_model = temp_model_factory.get_juju("sender")
    return sender_model


@pytest.fixture(scope="module")
def receiver_model(temp_model_factory):
    """Create and return a Juju instance for the receiver model."""
    receiver_model = temp_model_factory.get_juju("receiver")
    return receiver_model


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_istio_dependencies(istio_juju: Juju):
    """Deploy istio-k8s in istio-system model."""
    # The istio_juju fixture handles deployment, this test just ensures it runs
    # and validates istio-k8s is active
    status = istio_juju.status()
    assert istio_k8s.application_name in status.apps
    assert status.apps[istio_k8s.application_name].is_active


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_environment(
    sender_model: Juju,
    receiver_model: Juju,
    istio_beacon_charm,
    istio_beacon_resources,
    service_mesh_tester,
):
    """Deploy the istio-beacon charm and testers in sender and receiver models.

    Asserts that these come to active, but does not assert that policies are created correctly.
    """
    # Deploy the istio-beacon and sender in the sender model
    sender_model.deploy(
        istio_beacon_charm,
        app=APP_NAME,
        resources=istio_beacon_resources,
        trust=True,
        config={"model-on-mesh": "true"},
    )
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    sender_model.deploy(
        service_mesh_tester,
        app=SENDER,
        resources=resources,
        trust=True,
    )

    # Deploy the istio-beacon and receiver in the receiver model
    receiver_model.deploy(
        istio_beacon_charm,
        app=APP_NAME,
        resources=istio_beacon_resources,
        trust=True,
        config={"model-on-mesh": "true"},
    )
    receiver_model.deploy(
        service_mesh_tester,
        app=RECEIVER,
        resources=resources,
        trust=True,
    )

    # Offer everything that the receiver needs to consume in a single offer
    sender_model.cli(
        "offer",
        f"{sender_model.model}.{SENDER}:outbound,require-cmr-mesh",
        include_model=False,
    )
    receiver_model.cli(
        "consume",
        f"admin/{sender_model.model}.{SENDER}",
    )
    receiver_model.integrate(
        f"{SENDER}:outbound",
        f"{RECEIVER}:inbound",
    )
    receiver_model.integrate(
        f"{SENDER}:require-cmr-mesh",
        f"{RECEIVER}:provide-cmr-mesh",
    )

    # Establish the relation between the istio-beacon and the receiver
    receiver_model.integrate(APP_NAME, f"{RECEIVER}:service-mesh")

    # Wait for everything to settle
    sender_model.wait(
        lambda s: all_agents_idle(s, APP_NAME, SENDER) and all_active(s, APP_NAME, SENDER),
        timeout=1000,
        delay=5,
        successes=3,
    )
    receiver_model.wait(
        lambda s: all_agents_idle(s, APP_NAME, RECEIVER) and all_active(s, APP_NAME, RECEIVER),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.parametrize(
    "path, code",
    [
        # GET request to /foo and /bar/ should succeed because the receiver requests they're open
        ("/foo", 200),
        ("/bar/", 200),
        # GET request to /baz should fail because the receiver does not request it
        ("/nonexistent", 403),  # GET request to a non-existent path should fail
    ]
)
def test_sender_can_talk_to_receiver(
    sender_model: Juju,
    receiver_model: Juju,
    path: str,
    code: int,
):
    """Test that the single related sender can talk to the receiver at the expected paths."""
    assert_request_returns_http_code(
        sender_model,
        f"{SENDER}/0",
        f"http://{RECEIVER}.{receiver_model.model}:8080{path}",
        code=code,
    )
