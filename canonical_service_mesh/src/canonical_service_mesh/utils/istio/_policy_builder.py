# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio policy resource builder."""

import hashlib
import logging
from typing import List, Union

import pydantic
from lightkube.models.meta_v1 import ObjectMeta

from ...enums import PolicyTargetType
from ...k8s.types import LightkubeResourcesList
from ...k8s.types.istio import AuthorizationPolicy
from ...models.istio import (
    AuthorizationPolicySpec,
    From,
    Operation,
    PolicyTargetReference,
    Rule,
    Source,
    To,
    WorkloadSelector,
)
from .._juju import get_peer_identity_for_juju_application

logger = logging.getLogger(__name__)

POLICY_RESOURCE_TYPES = {
    "istio": {AuthorizationPolicy},
}


def _hash_pydantic_model(model: pydantic.BaseModel) -> str:
    """Hash a pydantic BaseModel object."""

    def _stable_hash(data):
        return hashlib.sha256(str(data).encode()).hexdigest()

    return _stable_hash(model)


def _generate_network_policy_name(app_name: str, model_name: str, mesh_policy) -> str:
    """Generate a unique name for the network policy resource.

    The name includes a hash of the MeshPolicy to avoid collisions and is truncated
    to fit within Kubernetes's 253-character limit.
    """
    target = mesh_policy.target_app_name or mesh_policy.target_service or "custom-selector"

    name = "-".join(
        [
            app_name,
            model_name,
            "policy",
            mesh_policy.source_app_name,
            mesh_policy.source_namespace,
            target,
            _hash_pydantic_model(mesh_policy)[:8],
        ]
    )
    if len(name) > 253:
        name = "-".join(
            [
                app_name,
                model_name,
                "policy",
                mesh_policy.source_app_name[:30],
                mesh_policy.source_namespace[:30],
                target[:30],
                _hash_pydantic_model(mesh_policy)[:8],
            ]
        )
    return name


def _build_source_rule(source_app_name: str, source_namespace: str) -> From:
    """Build a From rule with the source application's identity."""
    return From(
        source=Source(
            principals=[
                get_peer_identity_for_juju_application(source_app_name, source_namespace)
            ]
        )
    )


def _build_unit_policy(app_name, model_name, policy) -> AuthorizationPolicy:
    """Build an L4 authorization policy for a unit-targeted MeshPolicy."""
    valid_unit_policy = not any(
        endpoint.methods or endpoint.paths or endpoint.hosts
        for endpoint in policy.endpoints
    )
    if not valid_unit_policy:
        logger.error(
            f"UnitPolicy requested between {policy.source_app_name} and "
            f"{policy.target_app_name} is not created as it contains some disallowed "
            "policy attributes. UnitPolicy for Istio service mesh cannot contain "
            "paths, methods or hosts"
        )
        return None

    workload_selector = None
    if policy.target_app_name:
        workload_selector = WorkloadSelector(
            matchLabels={"app.kubernetes.io/name": policy.target_app_name}
        )
    if policy.target_selector_labels:
        workload_selector = WorkloadSelector(matchLabels=policy.target_selector_labels)

    return AuthorizationPolicy(
        metadata=ObjectMeta(
            name=_generate_network_policy_name(app_name, model_name, policy),
            namespace=policy.target_namespace,
        ),
        spec=AuthorizationPolicySpec(
            selector=workload_selector,
            rules=[
                Rule(
                    from_=[_build_source_rule(policy.source_app_name, policy.source_namespace)],
                    to=[
                        To(
                            operation=Operation(
                                ports=[str(p) for p in endpoint.ports]
                                if endpoint.ports
                                else [],
                            )
                        )
                        for endpoint in policy.endpoints
                    ],
                ),
            ],
        ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
    )


def _build_app_policy(app_name, model_name, policy) -> AuthorizationPolicy:
    """Build an L7 authorization policy for an app-targeted MeshPolicy."""
    target_service = policy.target_service or policy.target_app_name
    if policy.target_service is None:
        logger.info(
            f"Got policy for application '{policy.target_app_name}' that has no "
            f"target_service. Defaulting to application name."
        )
    if all([policy.target_service, policy.target_app_name]):
        logger.info(
            f"Got policy for application '{policy.target_app_name}' that has both "
            f"target_service and target_app_name. Using {target_service} for policy "
            f"target definition."
        )

    return AuthorizationPolicy(
        metadata=ObjectMeta(
            name=_generate_network_policy_name(app_name, model_name, policy),
            namespace=policy.target_namespace,
        ),
        spec=AuthorizationPolicySpec(
            targetRefs=[
                PolicyTargetReference(kind="Service", group="", name=target_service)
            ],
            rules=[
                Rule(
                    from_=[_build_source_rule(policy.source_app_name, policy.source_namespace)],
                    to=[
                        To(
                            operation=Operation(
                                ports=[str(p) for p in endpoint.ports]
                                if endpoint.ports
                                else [],
                                hosts=endpoint.hosts,
                                methods=endpoint.methods,
                                paths=endpoint.paths,
                            )
                        )
                        for endpoint in policy.endpoints
                    ],
                )
            ],
        ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
    )


def build_policy_resources_istio(
    app_name: str, model_name: str, policies: list
) -> Union[LightkubeResourcesList, List[None]]:
    """Build the required authorization policy resources for Istio service mesh."""
    authorization_policies = [None] * len(policies)
    for i, policy in enumerate(policies):
        if policy.target_type == PolicyTargetType.unit:
            authorization_policies[i] = _build_unit_policy(app_name, model_name, policy)
        elif policy.target_type == PolicyTargetType.app:
            authorization_policies[i] = _build_app_policy(app_name, model_name, policy)
        else:
            raise ValueError(
                "Failed to build requested istio authorization policy. "
                "Unknown target_type for policy."
            )
    return authorization_policies
