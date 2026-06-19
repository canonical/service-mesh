# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import MagicMock, patch

import scenario
from canonical_service_mesh.models.istio import JWTRule
from charmlibs.interfaces.istio_request_auth import JWTRule as InterfaceJWTRule

from charm import IstioIngressCharm


def _make_request_auth_relation(
    issuer="https://issuer.example.com",
    jwks_uri="https://issuer.example.com/jwks",
    remote_app_name="remote",
):
    """Create an istio-request-auth relation with JWT rule data in the remote app databag."""
    rules = [
        InterfaceJWTRule(
            issuer=issuer,
            jwks_uri=jwks_uri,
            forward_original_token=True,
        ).model_dump()
    ]
    return scenario.Relation(
        endpoint="istio-request-auth",
        interface="istio_request_auth",
        remote_app_name=remote_app_name,
        remote_app_data={"jwt_rules": json.dumps(rules)},
    )


def _make_malformed_request_auth_relation(remote_app_name="malformed-app"):
    """Create an istio-request-auth relation with an empty databag (no valid jwt_rules)."""
    return scenario.Relation(
        endpoint="istio-request-auth",
        interface="istio_request_auth",
        remote_app_name=remote_app_name,
        remote_app_data={},
    )


def _make_forward_auth_relation():
    """Create a forward-auth relation with a decisions address."""
    return scenario.Relation(
        endpoint="forward-auth",
        interface="forward_auth",
        remote_app_data={
            "decisions_address": "http://auth-service:80",
            "app_names": json.dumps(["my-app"]),
            "headers": json.dumps([]),
        },
    )


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------


def test_construct_request_authentication(istio_ingress_context):
    """Test that RA resource has correct targetRef, issuer, and jwksUri."""
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm

        jwt_rules = [
            JWTRule(
                issuer="https://issuer.example.com",
                jwksUri="https://issuer.example.com/jwks",
                forwardOriginalToken=True,
            )
        ]
        ra = charm._construct_request_authentication("my-app", jwt_rules)

        assert ra.metadata.name == f"request-auth-my-app-{charm.app.name}"
        assert ra.spec["targetRefs"][0]["kind"] == "Gateway"
        assert ra.spec["targetRefs"][0]["name"] == charm.app.name
        assert ra.spec["jwtRules"][0]["issuer"] == "https://issuer.example.com"
        assert ra.spec["jwtRules"][0]["jwksUri"] == "https://issuer.example.com/jwks"
        assert ra.spec["jwtRules"][0]["forwardOriginalToken"] is True


def test_construct_deny_without_jwt_policy(istio_ingress_context):
    """Test that DENY policy uses notRequestPrincipals targeting the Gateway."""
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        policy = charm._construct_deny_without_jwt_policy()

        assert policy.metadata.name == f"deny-without-jwt-{charm.app.name}"
        assert policy.spec["action"] == "DENY"
        assert policy.spec["targetRefs"][0]["kind"] == "Gateway"
        assert policy.spec["rules"][0]["from"][0]["source"]["notRequestPrincipals"] == ["*"]
        # No 'when' condition by default
        assert "when" not in policy.spec["rules"][0]


def test_construct_deny_without_jwt_policy_bearer_only(istio_ingress_context):
    """Test that bearer_only=True scopes the DENY policy to Bearer-token requests."""
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        policy = charm._construct_deny_without_jwt_policy(bearer_only=True)

        assert policy.spec["action"] == "DENY"
        assert policy.spec["rules"][0]["from"][0]["source"]["notRequestPrincipals"] == ["*"]
        # 'when' condition scopes to Bearer requests only
        when = policy.spec["rules"][0]["when"]
        assert len(when) == 1
        assert when[0]["key"] == "request.headers[authorization]"
        assert when[0]["values"] == ["Bearer *"]


def test_convert_to_jwt_rules(istio_ingress_context):
    """Test conversion from interface JWTRule models to Istio CRD JWTRule models."""
    interface_jwt_rules = [
        InterfaceJWTRule(
            issuer="https://issuer.example.com",
            jwks_uri="https://issuer.example.com/jwks",
            audiences=["my-audience"],
            forward_original_token=True,
        )
    ]
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        jwt_rules = charm._convert_to_jwt_rules(interface_jwt_rules)

        assert len(jwt_rules) == 1
        assert jwt_rules[0].issuer == "https://issuer.example.com"
        assert jwt_rules[0].jwksUri == "https://issuer.example.com/jwks"
        assert jwt_rules[0].audiences == ["my-audience"]
        assert jwt_rules[0].forwardOriginalToken is True


# ---------------------------------------------------------------------------
# _sync_request_authentication
# ---------------------------------------------------------------------------


@patch.object(IstioIngressCharm, "_get_request_auth_resource_manager")
def test_sync_ra_with_valid_data(mock_get_krm, istio_ingress_context):
    """Valid relation data produces a RequestAuthentication resource."""
    mock_krm = MagicMock()
    mock_get_krm.return_value = mock_krm

    relation = _make_request_auth_relation()
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=[relation], leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_request_authentication()

        mock_krm.reconcile.assert_called_once()
        resources = mock_krm.reconcile.call_args[0][0]
        assert len(resources) == 1
        assert resources[0].spec["jwtRules"][0]["issuer"] == "https://issuer.example.com"


@patch.object(IstioIngressCharm, "_get_request_auth_resource_manager")
def test_sync_ra_without_relation(mock_get_krm, istio_ingress_context):
    """No relation means reconcile with an empty list."""
    mock_krm = MagicMock()
    mock_get_krm.return_value = mock_krm

    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_request_authentication()

        mock_krm.reconcile.assert_called_once_with([])


@patch.object(IstioIngressCharm, "_get_request_auth_resource_manager")
def test_sync_ra_malformed_reconciles_empty(mock_get_krm, istio_ingress_context):
    """Malformed app data produces no RA resources (fail-closed via DENY policy)."""
    mock_krm = MagicMock()
    mock_get_krm.return_value = mock_krm

    malformed_relation = _make_malformed_request_auth_relation()
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=[malformed_relation], leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_request_authentication()

        mock_krm.reconcile.assert_called_once_with([])


@patch.object(IstioIngressCharm, "_get_request_auth_resource_manager")
def test_sync_ra_mixed_creates_ra_for_valid_only(mock_get_krm, istio_ingress_context):
    """Mixed valid and malformed apps: RA is created only for the valid app."""
    mock_krm = MagicMock()
    mock_get_krm.return_value = mock_krm

    valid_relation = _make_request_auth_relation()
    malformed_relation = _make_malformed_request_auth_relation()
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=[valid_relation, malformed_relation], leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_request_authentication()

        mock_krm.reconcile.assert_called_once()
        resources = mock_krm.reconcile.call_args[0][0]
        assert len(resources) == 1
        assert resources[0].spec["jwtRules"][0]["issuer"] == "https://issuer.example.com"


# ---------------------------------------------------------------------------
# _sync_deny_auth_policy – without forward-auth
# ---------------------------------------------------------------------------


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_no_relation(mock_get_prm, istio_ingress_context):
    """No request-auth relation → no DENY policy."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 0


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_valid_data_no_forward_auth(mock_get_prm, istio_ingress_context):
    """Valid request-auth, no forward-auth → DENY policy for all requests (no when)."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    relation = _make_request_auth_relation()
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=[relation], leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 1
        assert raw_policies[0].spec["action"] == "DENY"
        assert "when" not in raw_policies[0].spec["rules"][0]


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_malformed_data_no_forward_auth(mock_get_prm, istio_ingress_context):
    """Malformed request-auth, no forward-auth → DENY policy still created (fail-closed)."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    malformed_relation = _make_malformed_request_auth_relation()
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=[malformed_relation], leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 1
        assert raw_policies[0].spec["action"] == "DENY"
        assert "when" not in raw_policies[0].spec["rules"][0]


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_mixed_data_no_forward_auth(mock_get_prm, istio_ingress_context):
    """Mixed valid/malformed request-auth, no forward-auth → DENY policy for all requests."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    valid_relation = _make_request_auth_relation()
    malformed_relation = _make_malformed_request_auth_relation()
    with patch.object(IstioIngressCharm, "_is_ready"), istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=[valid_relation, malformed_relation], leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 1
        assert raw_policies[0].spec["action"] == "DENY"
        assert "when" not in raw_policies[0].spec["rules"][0]


# ---------------------------------------------------------------------------
# _sync_deny_auth_policy – with forward-auth
# ---------------------------------------------------------------------------


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_valid_data_with_forward_auth(mock_get_prm, istio_ingress_context):
    """Valid request-auth + forward-auth → DENY policy scoped to Bearer requests only."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    relations = [_make_request_auth_relation(), _make_forward_auth_relation()]
    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=relations, leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 1
        assert raw_policies[0].spec["action"] == "DENY"
        when = raw_policies[0].spec["rules"][0]["when"]
        assert when[0]["key"] == "request.headers[authorization]"
        assert when[0]["values"] == ["Bearer *"]


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_malformed_data_with_forward_auth(mock_get_prm, istio_ingress_context):
    """Malformed request-auth + forward-auth → DENY policy scoped to Bearer (fail-closed)."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    relations = [_make_malformed_request_auth_relation(), _make_forward_auth_relation()]
    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=relations, leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 1
        assert raw_policies[0].spec["action"] == "DENY"
        when = raw_policies[0].spec["rules"][0]["when"]
        assert when[0]["key"] == "request.headers[authorization]"
        assert when[0]["values"] == ["Bearer *"]


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_mixed_data_with_forward_auth(mock_get_prm, istio_ingress_context):
    """Mixed request-auth + forward-auth → DENY policy scoped to Bearer."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    relations = [
        _make_request_auth_relation(),
        _make_malformed_request_auth_relation(),
        _make_forward_auth_relation(),
    ]
    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=relations, leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 1
        assert raw_policies[0].spec["action"] == "DENY"
        when = raw_policies[0].spec["rules"][0]["when"]
        assert when[0]["key"] == "request.headers[authorization]"
        assert when[0]["values"] == ["Bearer *"]


@patch.object(IstioIngressCharm, "_get_deny_auth_policy_resource_manager")
def test_deny_policy_no_request_auth_with_forward_auth(mock_get_prm, istio_ingress_context):
    """Forward-auth only (no request-auth) → no DENY policy."""
    mock_prm = MagicMock()
    mock_get_prm.return_value = mock_prm

    relations = [_make_forward_auth_relation()]
    with istio_ingress_context(
        istio_ingress_context.on.update_status(),
        state=scenario.State(relations=relations, leader=True),
    ) as manager:
        charm: IstioIngressCharm = manager.charm
        charm._sync_deny_auth_policy()

        raw_policies = mock_prm.reconcile.call_args[1]["raw_policies"]
        assert len(raw_policies) == 0
