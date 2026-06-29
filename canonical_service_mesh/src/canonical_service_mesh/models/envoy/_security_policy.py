# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy Gateway SecurityPolicy resource models for Kubernetes."""

from typing import List, Optional

from pydantic import BaseModel


class LocalPolicyTargetRef(BaseModel):
    """A local (same-namespace) reference to a policy target resource."""

    group: str
    kind: str
    name: str


class BackendObjectRef(BaseModel):
    """A typed backend reference pointing at a specific group/kind resource."""

    group: str
    kind: str
    name: str
    namespace: Optional[str] = None


class ExtAuthHTTPService(BaseModel):
    """HTTP-based ext auth service configuration."""

    backendRefs: List[BackendObjectRef]  # noqa: N815
    path: Optional[str] = None


class ExtAuth(BaseModel):
    """External authentication configuration for a SecurityPolicy."""

    http: Optional[ExtAuthHTTPService] = None


class SecurityPolicySpec(BaseModel):
    """Spec of an Envoy Gateway SecurityPolicy resource."""

    targetRef: LocalPolicyTargetRef  # noqa: N815
    extAuth: Optional[ExtAuth] = None  # noqa: N815
