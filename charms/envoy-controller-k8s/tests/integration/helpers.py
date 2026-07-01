# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Live-cluster helpers for the envoy-controller-k8s integration tests."""

import logging

import yaml
from jubilant import Juju
from lightkube import ApiError, Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition

logger = logging.getLogger(__name__)

APP_NAME = "envoy-controller-k8s"
GATEWAY_CONTAINER = "envoy-gateway"
GATEWAY_SERVICE = "envoy-gateway"
CONFIG_PATH = "/etc/envoy-gateway/config.yaml"

# Gateway API CRDs the controller installs (subset asserted across features).
GATEWAY_API_CRDS = (
    "gatewayclasses.gateway.networking.k8s.io",
    "gateways.gateway.networking.k8s.io",
    "httproutes.gateway.networking.k8s.io",
    "grpcroutes.gateway.networking.k8s.io",
    "referencegrants.gateway.networking.k8s.io",
    "backendtlspolicies.gateway.networking.k8s.io",
)

EnvoyProxy = create_namespaced_resource(
    "gateway.envoyproxy.io", "v1alpha1", "EnvoyProxy", "envoyproxies"
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


def read_workload_file(juju: Juju, unit: str, container: str, path: str) -> str:
    """Read a file from a (distroless) workload container via pebble pull."""
    tmp = "/tmp/_probe_pull"
    juju.cli("exec", "--unit", unit, "--", _pebble(container, "pull", path, tmp))
    return juju.cli("exec", "--unit", unit, "--", f"cat {tmp}")


def envoy_gateway_config(juju: Juju) -> dict:
    """Load the Envoy Gateway config.yaml the charm rendered into the workload."""
    raw = read_workload_file(juju, f"{APP_NAME}/0", GATEWAY_CONTAINER, CONFIG_PATH)
    return yaml.safe_load(raw)


def envoy_proxy_spec(juju: Juju) -> dict:
    """Return the spec of the default EnvoyProxy resource (named after the app)."""
    obj = Client().get(EnvoyProxy, name=APP_NAME, namespace=juju.model)
    return obj.spec  # type: ignore[attr-defined]


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
