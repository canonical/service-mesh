#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""This module defines Pydantic schemas for various resources used in the Kiali config."""

from typing import Optional

from pydantic import BaseModel, Field


class AuthConfig(BaseModel):
    """Configuration for authentication."""

    strategy: str = "anonymous"


class DeploymentConfig(BaseModel):
    """Configuration for deployment."""

    view_only_mode: bool = True


class ExternalServiceConfig(BaseModel):
    """Configuration for an external service endpoint."""

    url: str


class TracingTempoConfig(BaseModel):
    """Configuration for Tempo tracing specifics."""

    org_id: str
    datasource_uid: str
    url_format: str


class TracingConfig(BaseModel):
    """Configuration for tracing functionality."""

    enabled: bool = False
    health_check_url: Optional[str] = None
    internal_url: str
    provider: str = "tempo"
    tempo_config: Optional[TracingTempoConfig] = None
    use_grpc: Optional[bool] = False
    external_url: Optional[str] = None
    grpc_port: Optional[int] = None


class PrometheusConfig(BaseModel):
    """Configuration for Prometheus service."""

    url: str


class GrafanaConfig(BaseModel):
    """Configuration for Grafana service."""

    enabled: bool = False
    # This is used by Kiali to present links to the user.  It should be accessible to the user.
    internal_url: str
    external_url: str


class ExternalServicesConfig(BaseModel):
    """Configuration for all external services used by Kiali."""

    prometheus: PrometheusConfig
    tracing: Optional[TracingConfig] = None
    grafana: Optional[GrafanaConfig] = None


class ServerConfig(BaseModel):
    """Configuration for the Kiali server."""

    port: int
    web_root: str = "/kiali"


class KialiConfigSpec(BaseModel):
    """Specification for the complete Kiali configuration."""

    auth: AuthConfig
    deployment: DeploymentConfig
    external_services: ExternalServicesConfig
    istio_namespace: str = Field(
        default="istio-system", description="Namespace for Istio resources"
    )
    server: ServerConfig
