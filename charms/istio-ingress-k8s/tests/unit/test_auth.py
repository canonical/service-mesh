# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch

import pytest
import scenario
from canonical_service_mesh.enums import Action
from ops import ActiveStatus, BlockedStatus

from charm import IstioIngressCharm


@pytest.mark.parametrize(
    "forward_auth_relation, expected_decision",
    [
        # When a forward-auth relation exists, its decisions address should be used.
        (
            scenario.Relation(
                endpoint="forward-auth",
                interface="forward_auth",
                remote_app_data={
                    "decisions_address": "http://auth-service:80",
                    "app_names": json.dumps(["my-app"]),
                    "headers": json.dumps([]),
                },
            ),
            "http://auth-service:80",
        ),
        # When no forward-auth relation exists, expected decision remains None.
        (None, None),
    ],
)
# to verify it is called
@patch.object(IstioIngressCharm, "_sync_ext_authz_auth_policy")
# to verify it is called
@patch.object(IstioIngressCharm, "_publish_to_istio_ingress_config_relation")
# to skip side effects
@patch.object(IstioIngressCharm, "_setup_proxy_pebble_service")
# so that gateway readiness passes
@patch.object(IstioIngressCharm, "_is_ready", return_value=True)
def test_ext_authz_setup(
    mock_is_ready,
    mock_setup,
    mock_publish,
    mock_sync,
    forward_auth_relation,
    expected_decision,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test external authorization configuration setup for when we have a valid ingress-config and different forward_auth situations."""
    relations = []
    if forward_auth_relation:
        relations.append(forward_auth_relation)

    ingress_config_relation = scenario.Relation(
        endpoint="istio-ingress-config",
        interface="istio_ingress_config",
        remote_app_data={"ext_authz_provider_name": "foo"},
    )
    relations.append(ingress_config_relation)

    state = scenario.State(relations=relations, leader=True)
    out = istio_ingress_context.run(istio_ingress_context.on.config_changed(), state)

    # forward_auth_headers will be None because the test fixture has empty headers
    mock_publish.assert_called_once_with(expected_decision, None)
    mock_sync.assert_called_once_with(expected_decision, [])
    assert isinstance(out.unit_status, ActiveStatus)
    assert out.unit_status.message.startswith("Serving at")


@pytest.mark.parametrize(
    "forward_auth_relation, ingress_config_relation, expected_message",
    [
        # Scenario A: No decisions address provided, with no ingress-config relation.
        (
            scenario.Relation(
                endpoint="forward-auth",
                interface="forward_auth",
                remote_app_data={},  # forward-auth relation has empty data
            ),
            None,  # ingress-config relation is absent
            "Authentication configuration incomplete; ingress is disabled.",
        ),
        # Scenario B: Decisions address provided, but ingress-config relation is present with empty data.
        (
            scenario.Relation(
                endpoint="forward-auth",
                interface="forward_auth",
                remote_app_data={
                    "decisions_address": "http://auth-service:80",
                    "app_names": json.dumps(["my-app"]),
                    "headers": json.dumps([]),
                },
            ),
            scenario.Relation(
                endpoint="istio-ingress-config",
                interface="istio_ingress_config",
                remote_app_data={},  # ingress-config relation exists but has empty data
            ),
            "Ingress configuration relation missing, yet valid authentication configuration are provided.",
        ),
    ],
)
def test_auth_and_ingress_incomplete(
    forward_auth_relation,
    ingress_config_relation,
    expected_message,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test external authorization configuration setup when the forward-auth or ingress-config relation is incomplete or missing."""
    relations = []
    if forward_auth_relation:
        relations.append(forward_auth_relation)
    if ingress_config_relation:
        relations.append(ingress_config_relation)

    state = scenario.State(relations=relations, leader=True)

    with patch.object(istio_ingress_charm, "_remove_gateway_resources") as mock_remove:
        out = istio_ingress_context.run(istio_ingress_context.on.config_changed(), state)
        assert isinstance(out.unit_status, BlockedStatus)
        assert out.unit_status.message == expected_message
        mock_remove.assert_called_once()


@pytest.mark.parametrize(
    "external_authorizer, unauthenticated_paths",
    [
        # No paths unauthenticated
        ("external_authorizer", []),
        # Some paths unauthenticated
        ("another_external_authorizer", ["/not-me", "/or-me"]),
    ],
)
def test_construct_ext_authz_policy(
    external_authorizer,
    unauthenticated_paths,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test that _construct_ext_authz_policy works correctly with and without unauthenticated paths."""
    # Initialize charm in test scenario
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(
            leader=True,
        ),
    ) as manager:
        charm: IstioIngressCharm = manager.charm

        # Call the method under test
        auth_policy = charm._construct_ext_authz_policy(
            ext_authz_provider_name=external_authorizer,
            unauthenticated_paths=unauthenticated_paths,
        )

        # Assert
        # Is a custom action with correct external authorizer
        assert auth_policy["spec"]["action"] == Action.custom
        assert auth_policy["spec"]["provider"]["name"] == external_authorizer

        if unauthenticated_paths:
            # Has a single rule with a single notPaths operation to omit any paths that should not be authenticated
            assert len(auth_policy["spec"]["rules"]) == 1
            assert len(auth_policy["spec"]["rules"][0]["to"]) == 1
            assert len(auth_policy["spec"]["rules"][0]["to"][0]["operation"]) == 1
            assert (
                auth_policy["spec"]["rules"][0]["to"][0]["operation"]["notPaths"]
                == unauthenticated_paths
            )
        else:
            # Has a single empty rule
            assert len(auth_policy["spec"]["rules"]) == 1
            assert auth_policy["spec"]["rules"][0] == {}


@pytest.mark.parametrize(
    "ip_blocks",
    [
        # Single CIDR - allow all
        (["0.0.0.0/0"]),
        # Multiple CIDRs
        (["10.0.0.0/8", "192.168.0.0/16"]),
    ],
)
def test_construct_external_traffic_auth_policy(
    ip_blocks,
    istio_ingress_charm,
    istio_ingress_context,
):
    """Test that _construct_external_traffic_auth_policy creates correct policy with IP blocks."""
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm

        auth_policy = charm._construct_external_traffic_auth_policy(ip_blocks=ip_blocks)

        # Is an allow action
        assert auth_policy["spec"]["action"] == Action.allow
        # Targets the Gateway
        assert len(auth_policy["spec"]["targetRefs"]) == 1
        assert auth_policy["spec"]["targetRefs"][0]["kind"] == "Gateway"
        assert auth_policy["spec"]["targetRefs"][0]["group"] == "gateway.networking.k8s.io"
        assert auth_policy["spec"]["targetRefs"][0]["name"] == charm.app.name
        # Has a single rule with correct ipBlocks
        assert len(auth_policy["spec"]["rules"]) == 1
        assert auth_policy["spec"]["rules"][0]["from"][0]["source"]["ipBlocks"] == ip_blocks
