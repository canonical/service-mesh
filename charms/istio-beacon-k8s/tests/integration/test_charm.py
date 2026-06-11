#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import httpx
import pytest
from helpers import (
    APP_NAME,
    assert_request_returns_http_code,
    assert_tcp_connectivity,
    istio_k8s,
    validate_labels,
    validate_mesh_labels_on_consumer,
    validate_policy_exists,
)
from jubilant import Juju, all_active, all_agents_idle
from lightkube.core.client import Client
from lightkube.resources.core_v1 import Pod

logger = logging.getLogger(__name__)


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
        lambda s: all_active(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )

@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_istio_beacon_is_on_the_mesh(juju: Juju):
    """Test that the istio-beacon is on the mesh."""
    model_name = juju.model

    c = Client()
    beacon_pod = c.get(Pod, name=f"{APP_NAME}-0", namespace=model_name)

    # Istio adds the following annotation to any pods on the mesh
    assert beacon_pod.metadata is not None
    assert beacon_pod.metadata.annotations is not None
    assert beacon_pod.metadata.annotations.get("ambient.istio.io/redirection", None) == "enabled"


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_service_mesh_apps(juju: Juju, service_mesh_tester):
    """Deploy the required tester apps onto the test model required for testing service mesh relation.

    This step deploys the tester apps and adds required relation between the testers and the
    istio beacon. This step must run before testing the service mesh relation. This step is branched
    off as the service mesh relation test is a parametrized test that needs to run multiple times without
    having to redeploy the tester apps.
    """
    # Deploy tester charms
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}

    # Applications that will be given authorization policies
    # receiver1 requires trust because the service-mesh library interacts with k8s objects.
    for app_name in ["receiver1", "sender1", "sender2", "sender3", "sender-scaled"]:
        juju.deploy(
            service_mesh_tester,
            app=app_name,
            resources=resources,
            trust=True,
        )

    # Add relations
    juju.integrate("receiver1:service-mesh", APP_NAME)
    juju.integrate("sender1:service-mesh", APP_NAME)
    juju.integrate("sender2:service-mesh", APP_NAME)
    juju.integrate("sender-scaled:service-mesh", APP_NAME)
    juju.integrate("receiver1:inbound", "sender1:outbound")
    juju.integrate("receiver1:inbound-unit", "sender2:outbound")

    apps = [APP_NAME, "receiver1", "sender1", "sender2", "sender3", "sender-scaled"]
    juju.wait(
        lambda s: all_agents_idle(s, *apps) and all_active(s,*apps),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("model_on_mesh", [False, True])
def test_mesh_config(juju: Juju, model_on_mesh):
    """Test model-on-mesh configuration."""
    model_name = juju.model

    # Set model-on-mesh config
    juju.config(APP_NAME, {"model-on-mesh": str(model_on_mesh).lower()})
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME) and all_active(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )

    # Validate labels based on state
    validate_labels(juju, APP_NAME, should_be_present=model_on_mesh)

    # Validate policy based on state
    if model_on_mesh:
        validate_policy_exists(juju, f"{APP_NAME}-{model_name}-policy-all-sources-modeloperator")
    else:
        with pytest.raises(httpx.HTTPStatusError):
            validate_policy_exists(juju, f"{APP_NAME}-{model_name}-policy-all-sources-modeloperator")


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("model_on_mesh", [False, True, False])
def test_mesh_labels_update_on_config_change(juju: Juju, model_on_mesh):
    """Test that toggling model-on-mesh updates mesh labels on consumer apps."""
    consumer_app = "receiver1"
    juju.config(consumer_app, {"auto-join-mesh": "true"})
    juju.config(APP_NAME, {"model-on-mesh": str(model_on_mesh).lower()})
    juju.wait(lambda s: all_agents_idle(s, APP_NAME, consumer_app) and all_active(s, APP_NAME, consumer_app), timeout=300, delay=5, successes=3)
    validate_mesh_labels_on_consumer(
        juju, APP_NAME, consumer_app, should_be_present=not model_on_mesh
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("model_on_mesh", [False, True])
def test_service_mesh_relation(juju: Juju, model_on_mesh):
    """Test if the service mesh relation correctly puts the tester applications on mesh and restricts traffic as expected.

    The test sets `auto-join-mesh` for the tester charm based on the `model_on_mesh` parameter.  So:
    * when `model_on_mesh=True` we set `auto-join-mesh=False` to test that the model has subscribed the apps
    * when `model_on_mesh=False` we set `auto-join-mesh=True` to test that the apps have subscribed themselves
    """
    model_name = juju.model

    # Configure model-on-mesh based on parameter
    juju.config(APP_NAME, {"model-on-mesh": str(model_on_mesh).lower()})

    # Wait for the mesh configuration for this model to be applied
    juju.wait(lambda s: all_agents_idle(s, APP_NAME) and all_active(s, APP_NAME), timeout=300, delay=5, successes=3)

    # configure auto-join for the apps based on model_on_mesh
    juju.config("receiver1", {"auto-join-mesh": str(not model_on_mesh).lower()})
    juju.config("sender1", {"auto-join-mesh": str(not model_on_mesh).lower()})
    juju.config("sender2", {"auto-join-mesh": str(not model_on_mesh).lower()})

    apps = [APP_NAME, "receiver1", "sender1", "sender2", "sender3"]
    juju.wait(
        lambda s: all_agents_idle(s, *apps) and all_active(s, *apps),
        timeout=1000,
        delay=5,
        successes=3,
    )

    # Assert that communication is correctly controlled via AppPolicy
    # sender1/0 can talk to receiver service on any combination of:
    # * port: [8080, 8081]
    # * path: [/foo, /bar/]
    # * method: [GET, POST]
    # but not the receiver workload or others
    assert_request_returns_http_code(
        juju,
        "sender1/0",
        "http://receiver1:8080/foo",
        code=200,
    )
    assert_request_returns_http_code(
        juju,
        "sender1/0",
        "http://receiver1:8081/foo",
        code=200,
    )
    assert_request_returns_http_code(
        juju,
        "sender1/0",
        "http://receiver1:8080/bar/",
        code=200,
    )
    assert_request_returns_http_code(
        juju,
        "sender1/0",
        "http://receiver1:8080/foo",
        method="post",
        code=200,
    )
    assert_request_returns_http_code(
        juju,
        "sender1/0",
        "http://receiver1:8080/foo",
        method="delete",
        code=403,
    )
    assert_request_returns_http_code(
        juju,
        "sender1/0",
        f"http://receiver1-0.receiver1-endpoints.{model_name}.svc.cluster.local:8080/foo",
        code=1,  # connection to the workload will be refused
    )

    # Assert that communication is correctly controlled via UnitPolicy
    # sender2/0 can talk to receiver workload on any route and any method.
    # but not to the receiver service or others
    # Connection to the service is not denied by default in the current istio-beacon design. It is denied here
    # because of the existence of AppPolicy above.
    assert_request_returns_http_code(
        juju,
        "sender2/0",
        "http://receiver1:8080/foo",
        code=403,
    )
    assert_request_returns_http_code(
        juju,
        "sender2/0",
        f"http://receiver1-0.receiver1-endpoints.{model_name}.svc.cluster.local:8080/foo",
        code=200,
    )
    assert_request_returns_http_code(
        juju,
        "sender2/0",
        f"http://receiver1-0.receiver1-endpoints.{model_name}.svc.cluster.local:8080/foo",
        method="delete",
        code=200,
    )
    assert_request_returns_http_code(
        juju,
        "sender2/0",
        f"http://receiver1-0.receiver1-endpoints.{model_name}.svc.cluster.local:8083/foo",
        method="delete",
        code=1,
    )

    # other service accounts should get a 403 error if model on mesh else should raise an exit code 1 as connection will be refused
    assert_request_returns_http_code(
        juju,
        "sender3/0",
        "http://receiver1:8080/foo",
        code=403 if model_on_mesh else 1,
    )
    assert_request_returns_http_code(
        juju,
        "sender3/0",
        f"http://receiver1-0.receiver1-endpoints.{model_name}.svc.cluster.local:8080/foo",
        code=1,  # connection to the workload will be refused
    )


@pytest.mark.abort_on_fail
def test_service_mesh_consumer_scaling(juju: Juju):
    """Tests if the ServiceMeshConsumer class allows the consumer app to scale without errors.

    Note: This test is stateful and will leave the sender-scaled deployment at a scale of 2.
    """
    # Scale up to 2 units (currently has 1)
    juju.add_unit("sender-scaled", num_units=1)

    juju.wait(
        lambda s: all_agents_idle(s, "sender-scaled") and all_active(s, "sender-scaled"),
        timeout=200,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("peer_communication", [True, False])
def test_peer_communication_in_scaled_service_mesh_consumer(juju: Juju, peer_communication):
    """Tests if the units in the scaled service mesh consumer is allowed to talk to each other based on the config."""
    model_name = juju.model

    juju.config("sender-scaled", {"peer-communication": str(peer_communication).lower()})

    assert_request_returns_http_code(
        juju,
        "sender-scaled/0",
        f"http://sender-scaled-1.sender-scaled-endpoints.{model_name}.svc.cluster.local:8080/foo",
        code=200 if peer_communication else 1,
    )


@pytest.mark.abort_on_fail
def test_modeloperator_rule(juju: Juju, service_mesh_tester, tester_resources, temp_model_factory):
    """Test that we allow anything, even off-mesh workloads, to talk to the modeloperator in beacon's namespace."""
    base_model = juju.model

    # Ensure model is on mesh
    juju.config(APP_NAME, {"model-on-mesh": "true"})

    # Create off-mesh model using temp_model_factory - respects --keep-models
    omm_juju = temp_model_factory.get_juju("off-mesh-model")

    # Deploy sender in off-mesh model
    resources = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}
    omm_juju.deploy(
        service_mesh_tester,
        app="sender",
        resources=resources,
        trust=True,
    )
    omm_juju.wait(lambda s: all_agents_idle(s, "sender") and all_active(s, "sender"), timeout=600, delay=5, successes=3)

    # Test TCP connectivity to modeloperator - we only care that the network connection can be established,
    # proving that the service mesh allows traffic from off-mesh workloads to the modeloperator
    assert_tcp_connectivity(
        omm_juju,
        "sender/0",
        f"modeloperator.{base_model}.svc.cluster.local",
        17071
    )
