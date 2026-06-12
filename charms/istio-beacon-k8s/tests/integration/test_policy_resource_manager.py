#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for PolicyResourceManager with policies and raw_policies."""

import logging
from unittest.mock import MagicMock

import pytest
from canonical_service_mesh.k8s.resource_manager import (
    PolicyResourceManager,
    create_charm_default_labels,
)
from canonical_service_mesh.k8s.types.istio import AuthorizationPolicy
from canonical_service_mesh.models.istio import (
    AuthorizationPolicySpec,
    From,
    Operation,
    PolicyTargetReference,
    Rule,
    Source,
    To,
)
from charmlibs.interfaces.service_mesh import (
    Endpoint,
    MeshPolicy,
    MeshType,
    PolicyTargetType,
)
from helpers import APP_NAME, AuthPolicy
from jubilant import Juju, all_active, all_agents_idle
from lightkube import Client
from lightkube.models.meta_v1 import ObjectMeta
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

PRM_TEST_LABEL_SCOPE = "prm-integration-test"


@pytest.fixture
def mock_charm(juju: Juju):
    charm = MagicMock()
    charm.app.name = "prm-test"
    charm.model.name = juju.model
    return charm


@pytest.fixture
def prm_labels(mock_charm):
    return create_charm_default_labels(
        mock_charm.app.name,
        mock_charm.model.name,
        scope=PRM_TEST_LABEL_SCOPE,
    )


@pytest.fixture
def lightkube_client():
    return Client(field_manager="prm-integration-test")


@pytest.fixture
def prm(mock_charm, lightkube_client, prm_labels):
    return PolicyResourceManager(
        charm=mock_charm,
        lightkube_client=lightkube_client,
        labels=prm_labels,
    )


@pytest.fixture
def cleanup_policies(prm):
    yield
    try:
        prm.delete(ignore_missing=True)
    except Exception as e:
        logger.warning(f"Error cleaning up policies: {e}")


@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(60), reraise=True)
def assert_policy_accepted(lightkube_client: Client, policy_name: str, namespace: str):
    """Assert that a policy has been accepted by the waypoint/ztunnel."""
    policy = lightkube_client.get(AuthPolicy, name=policy_name, namespace=namespace)
    assert policy.status is not None, f"Policy {policy_name} has no status yet"

    conditions = policy.status.get("conditions", [])  # type: ignore[union-attr]
    accepted = any(
        c.get("status") == "True" and c.get("reason") == "Accepted"
        for c in conditions
    )
    assert accepted, f"Policy {policy_name} not accepted. Conditions: {conditions}"


@pytest.mark.setup
@pytest.mark.abort_on_fail
def test_deploy_beacon(
    juju: Juju, istio_juju: Juju, istio_beacon_charm, istio_beacon_resources
):
    """Deploy istio-beacon with model-on-mesh enabled."""
    juju.deploy(
        istio_beacon_charm,
        app=APP_NAME,
        resources=istio_beacon_resources,
        trust=True,
        config={"model-on-mesh": "true"},
    )
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME) and all_active(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.abort_on_fail
def test_prm_reconcile_with_mesh_policies(
    istio_juju: Juju, juju: Juju, prm, cleanup_policies, lightkube_client
):
    """Test PRM reconciles MeshPolicy objects into AuthorizationPolicies."""
    model_name = juju.model
    assert model_name is not None

    mesh_policies = [
        MeshPolicy(
            source_namespace=model_name,
            source_app_name="test-sender",
            target_namespace=model_name,
            target_app_name=APP_NAME,
            target_type=PolicyTargetType.app,
            endpoints=[
                Endpoint(
                    ports=[8080],
                    methods=["GET"],  # type: ignore
                    paths=["/api"],
                )
            ],
        ),
    ]

    prm.reconcile(mesh_policies, MeshType.istio)

    policies = list(lightkube_client.list(AuthPolicy, namespace=model_name))
    prm_policies = [p for p in policies if PRM_TEST_LABEL_SCOPE in str(p.metadata.labels)]

    assert len(prm_policies) == 1, f"Expected 1 policy, found {len(prm_policies)}"
    assert prm_policies[0].spec["targetRefs"][0]["name"] == APP_NAME

    assert_policy_accepted(lightkube_client, prm_policies[0].metadata.name, model_name)


@pytest.mark.abort_on_fail
def test_prm_reconcile_with_raw_policies(
    istio_juju: Juju, juju: Juju, prm, cleanup_policies, lightkube_client
):
    """Test PRM reconciles raw AuthorizationPolicy objects."""
    model_name = juju.model
    assert model_name is not None

    raw_policy = AuthorizationPolicy(
        metadata=ObjectMeta(
            name="prm-test-raw-policy",
            namespace=model_name,
        ),
        spec=AuthorizationPolicySpec(
            targetRefs=[
                PolicyTargetReference(
                    kind="Service",
                    group="",
                    name=APP_NAME,
                )
            ],
            rules=[
                Rule(
                    from_=[  # type: ignore[call-arg]
                        From(
                            source=Source(
                                principals=[f"cluster.local/ns/{model_name}/sa/raw-sender"]
                            )
                        )
                    ],
                    to=[
                        To(
                            operation=Operation(
                                ports=["9090"],
                                methods=["POST"],  # type: ignore[arg-type]
                            )
                        )
                    ],
                )
            ],
        ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
    )

    prm.reconcile([], MeshType.istio, raw_policies=[raw_policy])

    created_policy = lightkube_client.get(
        AuthPolicy, name="prm-test-raw-policy", namespace=model_name
    )
    assert created_policy is not None
    assert created_policy.spec["targetRefs"][0]["name"] == APP_NAME

    assert_policy_accepted(lightkube_client, "prm-test-raw-policy", model_name)


@pytest.mark.abort_on_fail
def test_prm_reconcile_with_both_policies_and_raw_policies(
    istio_juju: Juju, juju: Juju, prm, cleanup_policies, lightkube_client
):
    """Test PRM reconciles both MeshPolicy and raw AuthorizationPolicy together."""
    model_name = juju.model
    assert model_name is not None

    mesh_policies = [
        MeshPolicy(
            source_namespace=model_name,
            source_app_name="mesh-sender",
            target_namespace=model_name,
            target_app_name=APP_NAME,
            target_type=PolicyTargetType.app,
            endpoints=[Endpoint(ports=[8080])],
        ),
    ]

    raw_policy = AuthorizationPolicy(
        metadata=ObjectMeta(
            name="prm-test-combined-raw-policy",
            namespace=model_name,
        ),
        spec=AuthorizationPolicySpec(
            targetRefs=[
                PolicyTargetReference(
                    kind="Service",
                    group="",
                    name=APP_NAME,
                )
            ],
            rules=[Rule()],
        ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
    )

    prm.reconcile(mesh_policies, MeshType.istio, raw_policies=[raw_policy])

    policies = list(lightkube_client.list(AuthPolicy, namespace=model_name))
    prm_policies = [p for p in policies if PRM_TEST_LABEL_SCOPE in str(p.metadata.labels)]

    assert len(prm_policies) == 2, f"Expected 2 policies, found {len(prm_policies)}"
    policy_names = [p.metadata.name for p in prm_policies]
    assert "prm-test-combined-raw-policy" in policy_names

    for policy in prm_policies:
        assert_policy_accepted(lightkube_client, policy.metadata.name, model_name)
