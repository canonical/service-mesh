# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio RequestAuthentication models for Kubernetes."""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from ._policy import PolicyTargetReference, WorkloadSelector


class ClaimToHeader(BaseModel):
    """ClaimToHeader maps a JWT claim to a request header."""

    header: str
    claim: str


class FromHeader(BaseModel):
    """FromHeader specifies a header location from which to extract a JWT."""

    name: str
    prefix: Optional[str] = None


class JWTRule(BaseModel):
    """JWTRule defines a JWT validation rule for RequestAuthentication."""

    issuer: str
    jwksUri: Optional[str] = None  # noqa: N815
    audiences: Optional[List[str]] = None
    forwardOriginalToken: Optional[bool] = None  # noqa: N815
    outputClaimToHeaders: Optional[List[ClaimToHeader]] = None  # noqa: N815
    fromHeaders: Optional[List[FromHeader]] = None  # noqa: N815


class RequestAuthenticationSpec(BaseModel):
    """RequestAuthenticationSpec defines the spec of an Istio RequestAuthentication resource."""

    targetRefs: Optional[List[PolicyTargetReference]] = Field(default=None)  # noqa: N815
    selector: Optional[WorkloadSelector] = Field(default=None)
    jwtRules: Optional[List[JWTRule]] = None  # noqa: N815

    @model_validator(mode="after")
    def validate_target(self):
        """Validate that at most one of targetRefs and selector is defined."""
        if self.targetRefs is not None and self.selector is not None:
            raise ValueError("At most one of targetRefs and selector can be set")
        return self
