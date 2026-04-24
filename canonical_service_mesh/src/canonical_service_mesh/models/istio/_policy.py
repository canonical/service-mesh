# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio authorization policy models for Kubernetes."""

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...enums import Action, Method


class PolicyTargetReference(BaseModel):
    """PolicyTargetReference defines the target of the policy for waypoint bound policies."""

    group: str
    kind: str
    name: str
    namespace: Optional[str] = None


class WorkloadSelector(BaseModel):
    """WorkloadSelector defines the target of the policy for ztunnel bound policies."""

    matchLabels: Dict[str, str]  # noqa: N815


class Source(BaseModel):
    """Source defines the source of the policy."""

    principals: Optional[List[str]] = None
    notPrincipals: Optional[List[str]] = None  # noqa: N815
    requestPrincipals: Optional[List[str]] = None  # noqa: N815
    notRequestPrincipals: Optional[List[str]] = None  # noqa: N815
    ipBlocks: Optional[List[str]] = None  # noqa: N815
    notIpBlocks: Optional[List[str]] = None  # noqa: N815
    namespaces: Optional[List[str]] = None


class From(BaseModel):
    """From defines the source of the policy."""

    source: Source


class Operation(BaseModel):
    """Operation defines the operation of the To model."""

    hosts: Optional[List[str]] = None
    notHosts: Optional[List[str]] = None  # noqa: N815
    ports: Optional[List[str]] = None
    methods: Optional[List[Method]] = None
    notMethods: Optional[List[Method]] = None  # noqa: N815
    paths: Optional[List[str]] = None
    notPaths: Optional[List[str]] = None  # noqa: N815


class To(BaseModel):
    """To defines the destination of the policy."""

    operation: Optional[Operation] = None


class Condition(BaseModel):
    """Condition defines the condition for the rule."""

    key: str
    values: Optional[List[str]] = None
    notValues: Optional[List[str]] = None  # noqa: N815


class Rule(BaseModel):
    """Rule defines a policy rule."""

    from_: Optional[List[From]] = Field(default=None, alias="from")
    to: Optional[List[To]] = None
    when: Optional[List[Condition]] = None
    model_config = ConfigDict(populate_by_name=True)


class Provider(BaseModel):
    """Provider defines the extension provider for the policy."""

    name: Optional[str] = None


class AuthorizationPolicySpec(BaseModel):
    """AuthorizationPolicySpec defines the structure of an Istio AuthorizationPolicy Kubernetes resource."""

    action: Action = Action.allow
    targetRefs: Optional[List[PolicyTargetReference]] = Field(default=None)  # noqa: N815
    selector: Optional[WorkloadSelector] = Field(default=None)
    rules: Optional[List[Rule]] = None
    provider: Optional[Provider] = Field(default=None)

    @model_validator(mode="after")
    def validate_target(self):
        """Validate that at most one of targetRefs and selector is defined."""
        if self.targetRefs is not None and self.selector is not None:
            raise ValueError("At most one of targetRefs and selector can be set")
        return self

    @model_validator(mode="after")
    def validate_provider_action(self):
        """Validate that CUSTOM action must be set when specifying extension providers."""
        if self.provider is not None and self.action is not Action.custom:
            raise ValueError("CUSTOM action must be set when specifying extension providers")
        return self
