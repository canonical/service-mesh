# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pydantic import ValidationError

from canonical_service_mesh.models.istio import (
    ClaimToHeader,
    FromHeader,
    JWTRule,
    PolicyTargetReference,
    RequestAuthenticationSpec,
    WorkloadSelector,
)


def test_cannot_set_both_targetrefs_and_selector():
    with pytest.raises(ValidationError, match="At most one of targetRefs and selector"):
        RequestAuthenticationSpec(
            targetRefs=[PolicyTargetReference(group="", kind="Service", name="svc")],
            selector=WorkloadSelector(matchLabels={"app": "test"}),
        )


def test_jwt_rule_with_claim_headers():
    rule = JWTRule(
        issuer="https://accounts.google.com",
        jwksUri="https://www.googleapis.com/jwks",
        audiences=["my-app"],
        forwardOriginalToken=True,
        outputClaimToHeaders=[ClaimToHeader(header="x-user", claim="sub")],
        fromHeaders=[FromHeader(name="Authorization", prefix="Bearer ")],
    )
    data = rule.model_dump(exclude_none=True)
    assert data["issuer"] == "https://accounts.google.com"
    assert data["outputClaimToHeaders"][0]["claim"] == "sub"
    assert data["fromHeaders"][0]["prefix"] == "Bearer "


def test_request_auth_with_selector():
    spec = RequestAuthenticationSpec(
        selector=WorkloadSelector(matchLabels={"app": "frontend"}),
        jwtRules=[JWTRule(issuer="https://issuer.example.com")],
    )
    assert spec.selector.matchLabels == {"app": "frontend"}
    assert spec.jwtRules[0].issuer == "https://issuer.example.com"
