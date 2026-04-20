# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace

import pytest

from canonical_service_mesh.enums import PolicyTargetType
from canonical_service_mesh.utils.istio import build_policy_resources_istio


def _make_endpoint(ports=None, methods=None, paths=None, hosts=None):
    return SimpleNamespace(ports=ports or [], methods=methods, paths=paths, hosts=hosts)


def _make_policy(
    source_app_name="src-app",
    source_namespace="src-ns",
    target_app_name="tgt-app",
    target_namespace="tgt-ns",
    target_type=PolicyTargetType.app,
    target_service=None,
    target_selector_labels=None,
    endpoints=None,
):
    return SimpleNamespace(
        source_app_name=source_app_name,
        source_namespace=source_namespace,
        target_app_name=target_app_name,
        target_namespace=target_namespace,
        target_type=target_type,
        target_service=target_service,
        target_selector_labels=target_selector_labels,
        endpoints=endpoints or [_make_endpoint(ports=[8080])],
    )


def test_build_app_policy():
    policies = [_make_policy(target_type=PolicyTargetType.app, target_service="my-svc")]
    resources = build_policy_resources_istio("beacon", "model", policies)

    assert len(resources) == 1
    resource = resources[0]
    spec = resource.spec
    assert spec["targetRefs"][0]["name"] == "my-svc"
    assert spec["rules"][0]["from"][0]["source"]["principals"] == [
        "cluster.local/ns/src-ns/sa/src-app"
    ]


def test_build_unit_policy():
    policies = [_make_policy(target_type=PolicyTargetType.unit)]
    resources = build_policy_resources_istio("beacon", "model", policies)

    assert len(resources) == 1
    resource = resources[0]
    spec = resource.spec
    assert spec["selector"]["matchLabels"]["app.kubernetes.io/name"] == "tgt-app"
    assert "targetRefs" not in spec


def test_unit_policy_rejected_with_l7_attributes():
    """Unit policies cannot have methods, paths, or hosts — they are L4 only."""
    policies = [
        _make_policy(
            target_type=PolicyTargetType.unit,
            endpoints=[_make_endpoint(ports=[80], methods=["GET"])],
        )
    ]
    resources = build_policy_resources_istio("beacon", "model", policies)
    assert resources[0] is None


def test_unit_policy_with_selector_labels():
    policies = [
        _make_policy(
            target_type=PolicyTargetType.unit,
            target_app_name=None,
            target_selector_labels={"custom": "label"},
        )
    ]
    resources = build_policy_resources_istio("beacon", "model", policies)
    assert resources[0].spec["selector"]["matchLabels"] == {"custom": "label"}


def test_unknown_target_type_raises():
    policies = [_make_policy()]
    policies[0].target_type = "unknown"
    with pytest.raises(ValueError, match="Unknown target_type"):
        build_policy_resources_istio("beacon", "model", policies)


def test_policy_name_contains_hash():
    """Policy names include a hash to avoid collisions."""
    policies = [_make_policy()]
    resources = build_policy_resources_istio("beacon", "model", policies)
    name = resources[0].metadata.name
    assert "policy" in name
    assert "beacon" in name
