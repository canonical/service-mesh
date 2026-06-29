# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy Gateway Backend resource models for Kubernetes."""

from typing import List, Optional

from pydantic import BaseModel


class FQDNEndpoint(BaseModel):
    """An FQDN-based endpoint for an Envoy Gateway Backend resource."""

    hostname: str
    port: int


class BackendEndpoint(BaseModel):
    """A single endpoint in an Envoy Gateway Backend resource."""

    fqdn: Optional[FQDNEndpoint] = None


class BackendSpec(BaseModel):
    """Spec of an Envoy Gateway Backend resource."""

    endpoints: List[BackendEndpoint]
