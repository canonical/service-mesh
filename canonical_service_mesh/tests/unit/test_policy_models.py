# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pydantic import ValidationError

from canonical_service_mesh.enums import Action
from canonical_service_mesh.models.istio import (
    AuthorizationPolicySpec,
    From,
    Operation,
    PolicyTargetReference,
    Rule,
    Source,
    To,
    WorkloadSelector,
)


def test_authorization_policy_defaults():
    spec = AuthorizationPolicySpec()
    assert spec.action == Action.allow
    assert spec.targetRefs is None
    assert spec.selector is None
    assert spec.rules is None


def test_cannot_set_both_targetrefs_and_selector():
    with pytest.raises(ValidationError, match="At most one of targetRefs and selector"):
        AuthorizationPolicySpec(
            targetRefs=[PolicyTargetReference(group="", kind="Service", name="svc")],
            selector=WorkloadSelector(matchLabels={"app": "test"}),
        )


def test_custom_action_required_for_provider():
    with pytest.raises(ValidationError, match="CUSTOM action must be set"):
        AuthorizationPolicySpec(
            action=Action.allow,
            provider={"name": "my-ext-provider"},
        )


def test_custom_action_with_provider_succeeds():
    spec = AuthorizationPolicySpec(
        action=Action.custom,
        provider={"name": "my-ext-provider"},
    )
    assert spec.provider.name == "my-ext-provider"


def test_rule_from_alias():
    """Rule.from_ uses 'from' alias for serialization."""
    rule = Rule(
        from_=[From(source=Source(principals=["cluster.local/ns/ns1/sa/app1"]))],
        to=[To(operation=Operation(ports=["8080"]))],
    )
    dumped = rule.model_dump(by_alias=True, exclude_none=True)
    assert "from" in dumped
    assert "from_" not in dumped


def test_full_policy_spec_roundtrip():
    spec = AuthorizationPolicySpec(
        action=Action.deny,
        targetRefs=[PolicyTargetReference(group="", kind="Service", name="frontend")],
        rules=[
            Rule(
                from_=[From(source=Source(principals=["cluster.local/ns/default/sa/backend"]))],
                to=[To(operation=Operation(ports=["443"], methods=["GET", "POST"]))],
            )
        ],
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    restored = AuthorizationPolicySpec.model_validate(data)
    assert restored.action == Action.deny
    assert restored.targetRefs[0].name == "frontend"
    assert restored.rules[0].to[0].operation.ports == ["443"]
