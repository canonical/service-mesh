# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Istio RequestAuthentication (fail-closed).

We test every combination of data state and auth mode to ensure the gateway
never silently falls open.  The matrix below summarises the scenarios and
the expected security outcome for each.

Scenario matrix
===============

Without forward-auth
--------------------
| # | Data state              | RA created?      | DENY created? | Traffic outcome               |
|---|-------------------------|------------------|---------------|-------------------------------|
| 1 | No relation             | No               | No            | Pass (no auth configured)     |
| 2 | All malformed / empty   | No               | Yes (global)  | Blocked – 403 (fail-closed)   |
| 3 | All valid               | Yes              | Yes (global)  | Token required – 403 / 200    |
| 4 | Mixed valid + malformed | Yes (valid only) | Yes (global)  | Token required – 403 / 200    |
| 5 | Valid → cleared         | Removed          | Yes (global)  | Blocked – 403 (fail-closed)   |
| 6 | Relation removed        | Removed          | Removed       | Pass (cleanup restores open)  |

With forward-auth (only utests. requires additional infra and hence should be covered by the solution level tests)
----------------------------------------------------------------------
| # | Data state              | RA created?      | DENY created?       | Traffic outcome                    |
|---|-------------------------|------------------|---------------------|------------------------------------|
| 7 | All malformed / empty   | No               | Yes (Bearer-only)   | Bearer blocked; non-Bearer → authz |
| 8 | All valid               | Yes              | Yes (Bearer-only)   | Bearer validated; non-Bearer → authz|
| 9 | Mixed valid + malformed | Yes (valid only) | Yes (Bearer-only)   | Bearer validated; non-Bearer → authz|

"""

import logging
from pathlib import Path

import pytest
import requests
import yaml
from helpers import (
    get_auth_policy_spec,
    get_k8s_service_address,
    get_request_auth_spec,
)
from jubilant import Juju, all_active

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
resources = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}

IPA_TESTER = "ra-tester"
IPA_TESTER_2 = "ra-tester-two"
MOCK_OAUTH2 = "mock-oauth2"
REQUEST_AUTH_RELATION = "istio-request-auth"
DENY_POLICY_NAME = f"deny-without-jwt-{APP_NAME}"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy_dependencies")
def test_deploy_dependencies(
    juju: Juju, istio_core_juju: Juju, tester_http_charm, tester_mock_oauth2_charm
):
    """Deploy tester-http and mock-oauth2-server charms."""
    juju.deploy(
        tester_http_charm,
        app=IPA_TESTER,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.deploy(
        tester_http_charm,
        app=IPA_TESTER_2,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.deploy(
        tester_mock_oauth2_charm,
        app=MOCK_OAUTH2,
        resources={"mock-oauth2-server-image": "ghcr.io/navikt/mock-oauth2-server:2.1.10"},
    )
    juju.wait(
        lambda s: all_active(s, IPA_TESTER, IPA_TESTER_2, MOCK_OAUTH2),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_deployment", depends=["test_deploy_dependencies"])
def test_deployment(juju: Juju, istio_ingress_charm, resources):
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


# Given testers exist
# When ingress is related
# Then all apps become active
@pytest.mark.dependency(name="test_relate_ingress", depends=["test_deployment"])
def test_relate_ingress(juju: Juju):
    juju.integrate(f"{IPA_TESTER}:ingress", f"{APP_NAME}:ingress")
    juju.integrate(f"{IPA_TESTER_2}:ingress", f"{APP_NAME}:ingress")
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER, IPA_TESTER_2),
        timeout=1000,
        delay=5,
        successes=3,
    )


# Given no request-auth relation
# When a request is sent
# Then it should succeed (200)
@pytest.mark.dependency(name="test_request_without_auth", depends=["test_relate_ingress"])
def test_request_without_auth(juju: Juju):
    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


# Given no JWT rules published
# When request-auth is related
# Then the charm stays active (fail-closed, no BlockedStatus)
@pytest.mark.dependency(
    name="test_malformed_relate_without_data",
    depends=["test_request_without_auth"],
)
def test_malformed_relate_without_data(juju: Juju):
    juju.integrate(
        f"{IPA_TESTER}:{REQUEST_AUTH_RELATION}", f"{APP_NAME}:{REQUEST_AUTH_RELATION}"
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


# Given malformed request-auth (empty databag)
# When the DENY policy is checked
# Then it exists, has no 'when' condition, and uses notRequestPrincipals
@pytest.mark.dependency(
    name="test_malformed_deny_policy_exists",
    depends=["test_malformed_relate_without_data"],
)
def test_malformed_deny_policy_exists(juju: Juju):
    policy_spec = get_auth_policy_spec(juju.model, DENY_POLICY_NAME)
    assert policy_spec is not None, f"DENY policy '{DENY_POLICY_NAME}' not found."
    assert policy_spec["action"] == "DENY"

    rules = policy_spec.get("rules", [])
    assert len(rules) >= 1
    assert "when" not in rules[0], "DENY policy should not have 'when' without forward-auth"
    not_principals = rules[0]["from"][0]["source"]["notRequestPrincipals"]
    assert "*" in not_principals


# Given malformed request-auth (empty databag)
# When the RA resource is checked
# Then no RA resource exists for the malformed app
@pytest.mark.dependency(
    name="test_malformed_no_ra_created",
    depends=["test_malformed_relate_without_data"],
)
def test_malformed_no_ra_created(juju: Juju):
    ra_name = f"request-auth-{IPA_TESTER}-{APP_NAME}"
    ra_spec = get_request_auth_spec(juju.model, ra_name)
    assert ra_spec is None, f"RA '{ra_name}' should NOT exist for malformed app."


# Given malformed request-auth with DENY policy active
# When a request is sent without a token
# Then it is denied (403)
@pytest.mark.dependency(
    name="test_malformed_traffic_blocked",
    depends=["test_malformed_deny_policy_exists"],
)
def test_malformed_traffic_blocked(juju: Juju):
    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url)
    assert resp.status_code == 403, f"Expected 403 (fail-closed), got {resp.status_code}"


# Given malformed test is done
# When the relation is removed
# Then the DENY policy is cleaned up
@pytest.mark.dependency(
    name="test_malformed_cleanup",
    depends=["test_malformed_traffic_blocked", "test_malformed_no_ra_created"],
)
def test_malformed_cleanup(juju: Juju):
    juju.remove_relation(
        f"{IPA_TESTER}:{REQUEST_AUTH_RELATION}", f"{APP_NAME}:{REQUEST_AUTH_RELATION}"
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )
    policy_spec = get_auth_policy_spec(juju.model, DENY_POLICY_NAME)
    assert policy_spec is None, "DENY policy should be removed after relation break."


# Given mock-oauth2 issuer info
# When JWT rules are published and request-auth is related
# Then the charm reconciles and stays active
@pytest.mark.dependency(
    name="test_configure_request_auth", depends=["test_malformed_cleanup"]
)
def test_configure_request_auth(juju: Juju):
    juju.integrate(f"{IPA_TESTER}:{REQUEST_AUTH_RELATION}", f"{APP_NAME}:{REQUEST_AUTH_RELATION}")

    issuer_result = juju.run(f"{MOCK_OAUTH2}/0", "get-issuer-info")
    issuer_url = issuer_result.results["issuer"]
    jwks_url = issuer_result.results["jwks-url"]

    juju.run(
        f"{IPA_TESTER}/0",
        "set-request-auth",
        {"issuer": issuer_url, "jwks-uri": jwks_url},
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


# Given valid JWT rules
# When the RA resource is checked
# Then it has the correct issuer and targets the Gateway
@pytest.mark.dependency(
    name="test_request_authentication_resource", depends=["test_configure_request_auth"]
)
def test_request_authentication_resource(juju: Juju):
    ra_name = f"request-auth-{IPA_TESTER}-{APP_NAME}"
    ra_spec = get_request_auth_spec(juju.model, ra_name)
    assert ra_spec is not None, f"RequestAuthentication '{ra_name}' not found."
    assert ra_spec["targetRefs"][0]["kind"] == "Gateway"

    jwt_rules = ra_spec["jwtRules"]
    assert len(jwt_rules) >= 1

    issuer_result = juju.run(f"{MOCK_OAUTH2}/0", "get-issuer-info")
    assert jwt_rules[0]["issuer"] == issuer_result.results["issuer"]


# Given valid request-auth without forward-auth
# When the DENY policy is checked
# Then it exists with no 'when' condition (applies to all requests)
@pytest.mark.dependency(
    name="test_deny_policy_exists", depends=["test_configure_request_auth"]
)
def test_deny_policy_exists(juju: Juju):
    policy_spec = get_auth_policy_spec(juju.model, DENY_POLICY_NAME)
    assert policy_spec is not None, f"DENY policy '{DENY_POLICY_NAME}' not found."
    assert policy_spec["action"] == "DENY"

    rules = policy_spec.get("rules", [])
    assert len(rules) >= 1
    assert "when" not in rules[0], "DENY should not have 'when' without forward-auth"
    not_principals = rules[0]["from"][0]["source"]["notRequestPrincipals"]
    assert "*" in not_principals


# Given valid request-auth
# When a request is sent without a token
# Then it is denied (403)
@pytest.mark.dependency(
    name="test_request_denied_without_token",
    depends=["test_deny_policy_exists"],
)
def test_request_denied_without_token(juju: Juju):
    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url)
    assert resp.status_code == 403, f"Expected 403 without token, got {resp.status_code}"


# Given valid request-auth
# When a request is sent with a valid JWT
# Then it succeeds (200)
@pytest.mark.dependency(
    name="test_request_allowed_with_valid_token",
    depends=["test_deny_policy_exists"],
)
def test_request_allowed_with_valid_token(juju: Juju):
    token_result = juju.run(f"{MOCK_OAUTH2}/0", "get-token")
    access_token = token_result.results["access-token"]

    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url, headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200, f"Expected 200 with valid token, got {resp.status_code}"


# Given a valid app with request-auth
# When a second app relates with an empty databag (malformed)
# Then the charm stays active
@pytest.mark.dependency(
    name="test_mixed_add_malformed_app",
    depends=["test_request_allowed_with_valid_token", "test_request_denied_without_token"],
)
def test_mixed_add_malformed_app(juju: Juju):
    juju.integrate(
        f"{IPA_TESTER_2}:{REQUEST_AUTH_RELATION}", f"{APP_NAME}:{REQUEST_AUTH_RELATION}"
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER, IPA_TESTER_2),
        timeout=1000,
        delay=5,
        successes=3,
    )


# Given mixed valid and malformed apps
# When RA resources are checked
# Then only the valid app has an RA resource
@pytest.mark.dependency(
    name="test_mixed_valid_app_has_ra",
    depends=["test_mixed_add_malformed_app"],
)
def test_mixed_valid_app_has_ra(juju: Juju):
    ra_name = f"request-auth-{IPA_TESTER}-{APP_NAME}"
    ra_spec = get_request_auth_spec(juju.model, ra_name)
    assert ra_spec is not None, f"RA '{ra_name}' should exist for valid app."
    assert len(ra_spec["jwtRules"]) >= 1


# Given mixed valid and malformed apps
# When RA resources are checked
# Then the malformed app has no RA resource
@pytest.mark.dependency(
    name="test_mixed_malformed_app_has_no_ra",
    depends=["test_mixed_add_malformed_app"],
)
def test_mixed_malformed_app_has_no_ra(juju: Juju):
    ra_name = f"request-auth-{IPA_TESTER_2}-{APP_NAME}"
    ra_spec = get_request_auth_spec(juju.model, ra_name)
    assert ra_spec is None, f"RA '{ra_name}' should NOT exist for malformed app."


# Given mixed valid and malformed apps
# When the DENY policy is checked
# Then it is still present
@pytest.mark.dependency(
    name="test_mixed_deny_policy_still_exists",
    depends=["test_mixed_add_malformed_app"],
)
def test_mixed_deny_policy_still_exists(juju: Juju):
    policy_spec = get_auth_policy_spec(juju.model, DENY_POLICY_NAME)
    assert policy_spec is not None
    assert policy_spec["action"] == "DENY"


# Given mixed valid and malformed apps with DENY policy
# When a request is sent without a token
# Then it is denied (403)
@pytest.mark.dependency(
    name="test_mixed_traffic_denied_without_token",
    depends=["test_mixed_deny_policy_still_exists"],
)
def test_mixed_traffic_denied_without_token(juju: Juju):
    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url)
    assert resp.status_code == 403, f"Expected 403 without token, got {resp.status_code}"


# Given mixed valid and malformed apps
# When a request is sent with a valid token
# Then it succeeds (200)
@pytest.mark.dependency(
    name="test_mixed_traffic_allowed_with_valid_token",
    depends=["test_mixed_deny_policy_still_exists"],
)
def test_mixed_traffic_allowed_with_valid_token(juju: Juju):
    token_result = juju.run(f"{MOCK_OAUTH2}/0", "get-token")
    access_token = token_result.results["access-token"]

    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url, headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200, f"Expected 200 with valid token, got {resp.status_code}"


# Given mixed test is done
# When the malformed relation is removed
# Then cleanup succeeds
@pytest.mark.dependency(
    name="test_mixed_cleanup",
    depends=[
        "test_mixed_traffic_denied_without_token",
        "test_mixed_traffic_allowed_with_valid_token",
        "test_mixed_valid_app_has_ra",
        "test_mixed_malformed_app_has_no_ra",
    ],
)
def test_mixed_cleanup(juju: Juju):
    juju.remove_relation(
        f"{IPA_TESTER_2}:{REQUEST_AUTH_RELATION}", f"{APP_NAME}:{REQUEST_AUTH_RELATION}"
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER, IPA_TESTER_2),
        timeout=1000,
        delay=5,
        successes=3,
    )


# Given valid JWT rules published
# When the rules are cleared (databag emptied)
# Then the charm stays active
@pytest.mark.dependency(
    name="test_clear_jwt_rules",
    depends=["test_mixed_cleanup"],
)
def test_clear_jwt_rules(juju: Juju):
    juju.run(f"{IPA_TESTER}/0", "clear-request-auth")
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


# Given cleared JWT rules
# When the RA resource is checked
# Then it is removed
@pytest.mark.dependency(
    name="test_cleared_ra_removed",
    depends=["test_clear_jwt_rules"],
)
def test_cleared_ra_removed(juju: Juju):
    ra_name = f"request-auth-{IPA_TESTER}-{APP_NAME}"
    ra_spec = get_request_auth_spec(juju.model, ra_name)
    assert ra_spec is None, f"RA '{ra_name}' should be removed after clearing rules."


# Given cleared JWT rules with relation still connected
# When the DENY policy is checked
# Then it remains active (fail-closed)
@pytest.mark.dependency(
    name="test_cleared_deny_policy_remains",
    depends=["test_clear_jwt_rules"],
)
def test_cleared_deny_policy_remains(juju: Juju):
    policy_spec = get_auth_policy_spec(juju.model, DENY_POLICY_NAME)
    assert policy_spec is not None, "DENY policy should remain when relation is connected."
    assert policy_spec["action"] == "DENY"


# Given cleared JWT rules with DENY policy active
# When a request is sent
# Then it is denied (403)
@pytest.mark.dependency(
    name="test_cleared_traffic_blocked",
    depends=["test_cleared_deny_policy_remains"],
)
def test_cleared_traffic_blocked(juju: Juju):
    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url)
    assert resp.status_code == 403, f"Expected 403 after clearing rules, got {resp.status_code}"


# Given request-auth relation exists
# When the relation is removed
# Then RA and DENY policy are cleaned up
@pytest.mark.dependency(
    name="test_remove_request_auth_relation",
    depends=["test_cleared_traffic_blocked"],
)
def test_remove_request_auth_relation(juju: Juju):
    juju.remove_relation(
        f"{IPA_TESTER}:{REQUEST_AUTH_RELATION}", f"{APP_NAME}:{REQUEST_AUTH_RELATION}"
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )

    ra_name = f"request-auth-{IPA_TESTER}-{APP_NAME}"
    ra_spec = get_request_auth_spec(juju.model, ra_name)
    assert ra_spec is None, f"Expected RA '{ra_name}' to be removed."

    policy_spec = get_auth_policy_spec(juju.model, DENY_POLICY_NAME)
    assert policy_spec is None, "Expected DENY policy to be removed."


# Given no request-auth relation
# When a request is sent
# Then it succeeds (200)
@pytest.mark.dependency(
    name="test_request_allowed_after_relation_break",
    depends=["test_remove_request_auth_relation"],
)
def test_request_allowed_after_relation_break(juju: Juju):
    istio_ingress_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    tester_url = f"http://{istio_ingress_address}/{juju.model}-{IPA_TESTER}"
    resp = requests.get(tester_url)
    assert resp.status_code == 200, f"Expected 200 after relation break, got {resp.status_code}"
