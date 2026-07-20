# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy Gateway shared telemetry models for Kubernetes."""

from typing import List, Optional

from pydantic import BaseModel, Field


class OpenTelemetrySink(BaseModel):
    """An OpenTelemetry metrics sink target (host + port).

    Matches the Envoy Gateway ``openTelemetry`` metric sink schema used by both
    ``EnvoyGateway.telemetry`` (control plane) and ``EnvoyProxy.spec.telemetry``
    (data plane).
    """

    host: str
    port: int


class MetricSink(BaseModel):
    """A single Envoy Gateway metrics sink entry."""

    type: str = "OpenTelemetry"
    openTelemetry: OpenTelemetrySink  # noqa: N815


class MetricsConfig(BaseModel):
    """Envoy metrics configuration carrying one or more sinks."""

    sinks: List[MetricSink] = Field(default_factory=list)


class TelemetryConfig(BaseModel):
    """Envoy telemetry configuration."""

    metrics: Optional[MetricsConfig] = None
