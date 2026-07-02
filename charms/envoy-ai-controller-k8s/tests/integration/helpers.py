# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Live-cluster helpers for the envoy-ai-controller-k8s integration tests."""

import logging

import yaml
from jubilant import Juju
from lightkube import ApiError, Client
from lightkube.resources.admissionregistration_v1 import MutatingWebhookConfiguration
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition

logger = logging.getLogger(__name__)

APP_NAME = "envoy-ai-controller-k8s"
CONTAINER = "ai-gateway"
SERVICE = "ai-gateway"

EXTENSION_SERVER_PORT = 1063
WEBHOOK_PORT = 9443

# The controller names the webhook "<config-name>.<model-namespace>" at startup.
WEBHOOK_CONFIG_NAME = "envoy-ai-gateway-gateway-pod-mutator"

# AI Gateway CRDs the controller installs from src/crds/ai-gateway/.
AI_GATEWAY_CRDS = (
    "aigatewayroutes.aigateway.envoyproxy.io",
    "aiservicebackends.aigateway.envoyproxy.io",
    "backendsecuritypolicies.aigateway.envoyproxy.io",
    "gatewayconfigs.aigateway.envoyproxy.io",
    "mcproutes.aigateway.envoyproxy.io",
    "quotapolicies.aigateway.envoyproxy.io",
)


def crd_exists(name: str) -> bool:
    """Return True if a CustomResourceDefinition with ``name`` exists on the cluster."""
    try:
        Client().get(CustomResourceDefinition, name=name)
        return True
    except ApiError as e:
        if e.status.code == 404:
            return False
        raise


def webhook_name(model: str) -> str:
    """Return the cluster-scoped ExtProc webhook config name for ``model``."""
    return f"{WEBHOOK_CONFIG_NAME}.{model}"


def get_ext_proc_webhook(model: str) -> MutatingWebhookConfiguration | None:
    """Return the ExtProc MutatingWebhookConfiguration, or None if absent."""
    try:
        return Client().get(MutatingWebhookConfiguration, name=webhook_name(model))
    except ApiError as e:
        if e.status.code == 404:
            return None
        raise


def _pebble(container: str, *args: str) -> str:
    """Build a pebble invocation against a workload container's socket."""
    socket = f"/charm/containers/{container}/pebble.socket"
    return f"PEBBLE_SOCKET={socket} /charm/bin/pebble " + " ".join(args)


def pebble_service_active(juju: Juju, unit: str, container: str, service: str) -> bool:
    """Return True if ``service`` reports Current=active in the workload's pebble."""
    out = juju.cli("exec", "--unit", unit, "--", _pebble(container, "services", service))
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == service:
            return parts[2] == "active"
    return False


def published_app_data(juju: Juju, publisher: str, peer: str) -> dict:
    """Return the app databag ``publisher`` publishes, read from ``peer``'s unit.

    ``juju show-unit`` omits an application's own databag when you query that
    application's unit, so the publisher's data must be read from the peer on the
    other end of the relation (where it appears under ``application-data``).
    """
    raw = juju.cli("show-unit", f"{peer}/0", "--format", "yaml")
    data = yaml.safe_load(raw)
    for rel in data[f"{peer}/0"].get("relation-info", []):
        units = rel.get("related-units", {})
        if any(u.split("/")[0] == publisher for u in units):
            return rel.get("application-data", {})
    return {}
