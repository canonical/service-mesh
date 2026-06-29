# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""EnvoyProxy resource spec models for Kubernetes."""

from typing import Any, List, Optional

from pydantic import BaseModel

from ._telemetry import TelemetryConfig


class JSONPatchOperation(BaseModel):
    """An RFC 6902 JSON Patch operation applied to the Envoy bootstrap."""

    op: str
    path: str
    value: Optional[Any] = None


class ProxyBootstrap(BaseModel):
    """Override or patch the Envoy bootstrap of the managed proxy fleet.

    Mirrors Envoy Gateway's ``ProxyBootstrap``: ``type`` selects the override
    strategy (``Replace``, ``Merge``, or ``JSONPatch``); ``value`` is a full
    bootstrap YAML string (for ``Replace``/``Merge``); ``jsonPatches`` is a list
    of RFC 6902 operations applied to the default bootstrap (for ``JSONPatch``).
    """

    type: Optional[str] = None
    value: Optional[str] = None
    jsonPatches: Optional[List[JSONPatchOperation]] = None  # noqa: N815


class EnvoyProxySpec(BaseModel):
    """Spec of a default EnvoyProxy resource.

    Carries an optional Envoy bootstrap override (e.g. to inject fixed
    Juju-topology stats tags via a JSON patch) and an optional OpenTelemetry
    metrics sink.
    """

    bootstrap: Optional[ProxyBootstrap] = None
    telemetry: Optional[TelemetryConfig] = None
