# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy Gateway resource models."""

from ._backend import (
    BackendEndpoint,
    BackendSpec,
    FQDNEndpoint,
)
from ._envoy_proxy import (
    EnvoyProxySpec,
    JSONPatchOperation,
    ProxyBootstrap,
)
from ._security_policy import (
    BackendObjectRef,
    ExtAuth,
    ExtAuthHTTPService,
    LocalPolicyTargetRef,
    SecurityPolicySpec,
)
from ._telemetry import (
    MetricsConfig,
    MetricSink,
    OpenTelemetrySink,
    TelemetryConfig,
)

__all__ = [
    "BackendEndpoint",
    "BackendObjectRef",
    "BackendSpec",
    "EnvoyProxySpec",
    "ExtAuth",
    "ExtAuthHTTPService",
    "FQDNEndpoint",
    "JSONPatchOperation",
    "LocalPolicyTargetRef",
    "MetricSink",
    "MetricsConfig",
    "OpenTelemetrySink",
    "ProxyBootstrap",
    "SecurityPolicySpec",
    "TelemetryConfig",
]
