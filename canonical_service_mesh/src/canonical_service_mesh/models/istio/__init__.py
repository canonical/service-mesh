# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio-specific models."""

from ._auth import (
    ClaimToHeader,
    FromHeader,
    JWTRule,
    RequestAuthenticationSpec,
)
from ._policy import (
    AuthorizationPolicySpec,
    Condition,
    From,
    Operation,
    PolicyTargetReference,
    Provider,
    Rule,
    Source,
    To,
    WorkloadSelector,
)

__all__ = [
    "AuthorizationPolicySpec",
    "ClaimToHeader",
    "Condition",
    "From",
    "FromHeader",
    "JWTRule",
    "Operation",
    "PolicyTargetReference",
    "Provider",
    "RequestAuthenticationSpec",
    "Rule",
    "Source",
    "To",
    "WorkloadSelector",
]
