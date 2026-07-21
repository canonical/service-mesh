# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Live-cluster helpers for the envoy-ingress-k8s integration tests."""

import logging
from typing import Optional

import requests
import yaml
from canonical_service_mesh.k8s.types.gateway_api import Gateway, GatewayClass, HTTPRoute
from jubilant import Juju
from lightkube import ApiError, Client
from lightkube.resources.core_v1 import Pod, Secret

logger = logging.getLogger(__name__)

APP_NAME = "envoy-ingress-k8s"
CONTROLLER_APP = "envoy-controller-k8s"
CONTROLLER_CHANNEL = "latest/edge"
GATEWAY_CLASS_NAME = "envoy"
GATEWAY_CONTROLLER_NAME = "gateway.envoyproxy.io/gatewayclass-controller"
HTTP_LISTENER_NAME = "http"
HTTPS_LISTENER_NAME = "https"


def _conditions(obj) -> list:
    """Return the ``.status.conditions`` list of a lightkube object, or []."""
    status = (getattr(obj, "status", None) or {})
    return status.get("conditions", []) if isinstance(status, dict) else []


def gateway_class_accepted(name: str = GATEWAY_CLASS_NAME) -> bool:
    """Return True if the GatewayClass has an Accepted=True condition."""
    try:
        gc = Client().get(GatewayClass, name=name)
    except ApiError as e:
        if e.status.code == 404:
            return False
        raise
    return any(
        c.get("type") == "Accepted" and c.get("status") == "True" for c in _conditions(gc)
    )


def gateway_class_controller(name: str = GATEWAY_CLASS_NAME) -> Optional[str]:
    """Return the ``spec.controllerName`` of the GatewayClass, or None."""
    try:
        gc = Client().get(GatewayClass, name=name)
    except ApiError:
        return None
    spec = getattr(gc, "spec", None) or {}
    return spec.get("controllerName") if isinstance(spec, dict) else None


def get_gateway(model: str, name: str = APP_NAME):
    """Return the Gateway object in ``model``, or None if absent."""
    try:
        return Client().get(Gateway, name=name, namespace=model)
    except ApiError:
        return None


def gateway_programmed(model: str, name: str = APP_NAME) -> bool:
    """Return True if the Gateway has a Programmed=True condition."""
    gw = get_gateway(model, name)
    if gw is None:
        return False
    return any(
        c.get("type") == "Programmed" and c.get("status") == "True" for c in _conditions(gw)
    )


def gateway_listener_names(model: str, name: str = APP_NAME) -> list:
    """Return the listener names declared on the Gateway spec."""
    gw = get_gateway(model, name)
    if gw is None:
        return []
    spec = getattr(gw, "spec", None) or {}
    listeners = spec.get("listeners", []) if isinstance(spec, dict) else []
    return [ln.get("name") for ln in listeners]


def gateway_listener(model: str, listener_name: str, name: str = APP_NAME) -> Optional[dict]:
    """Return the listener dict with ``listener_name`` from the Gateway spec, or None."""
    gw = get_gateway(model, name)
    if gw is None:
        return None
    spec = getattr(gw, "spec", None) or {}
    for ln in spec.get("listeners", []) if isinstance(spec, dict) else []:
        if ln.get("name") == listener_name:
            return ln
    return None


def gateway_addresses(model: str, name: str = APP_NAME) -> list:
    """Return the load-balancer addresses assigned to the Gateway."""
    gw = get_gateway(model, name)
    status = (getattr(gw, "status", None) or {}) if gw is not None else {}
    addresses = status.get("addresses", []) if isinstance(status, dict) else []
    return [a["value"] for a in addresses if a.get("value")]


def httproute_exists(model: str, name: str) -> bool:
    """Return True if an HTTPRoute named ``name`` exists in ``model``."""
    try:
        Client().get(HTTPRoute, name=name, namespace=model)
        return True
    except ApiError as e:
        if e.status.code == 404:
            return False
        raise


def get_httproute(model: str, name: str):
    """Return the HTTPRoute object, or None if absent."""
    try:
        return Client().get(HTTPRoute, name=name, namespace=model)
    except ApiError:
        return None


def list_httproutes(model: str) -> list:
    """Return the names of every HTTPRoute in ``model``."""
    return [r.metadata.name for r in Client().list(HTTPRoute, namespace=model)]


def tls_secret_exists(model: str, name: str) -> bool:
    """Return True if a kubernetes.io/tls Secret named ``name`` exists in ``model``."""
    try:
        secret = Client().get(Secret, name=name, namespace=model)
        return secret.type == "kubernetes.io/tls"
    except ApiError as e:
        if e.status.code == 404:
            return False
        raise


def envoy_proxy_pods(model: str, gateway: str = APP_NAME) -> list:
    """Return pods Envoy Gateway provisioned for the Gateway (by owning-gateway label)."""
    selector = {"gateway.envoyproxy.io/owning-gateway-name": gateway}
    return list(Client().list(Pod, namespace=model, labels=selector))


def published_ingress_url(juju: Juju, requirer: str) -> Optional[str]:
    """Return the ingress URL the charm published to ``requirer`` on the ingress relation.

    ``juju show-unit`` omits an app's own databag, so the provider's ``ingress`` data
    is read from the requirer unit where it appears under ``application-data``.
    """
    raw = juju.cli("show-unit", f"{requirer}/0", "--format", "yaml")
    data = yaml.safe_load(raw)
    for rel in data[f"{requirer}/0"].get("relation-info", []):
        app_data = rel.get("application-data", {})
        if "ingress" in app_data:
            return yaml.safe_load(app_data["ingress"]).get("url")
    return None


def http_get_ok(url: str, headers: Optional[dict] = None) -> bool:
    """Return True if a GET to ``url`` returns HTTP 200."""
    try:
        return requests.get(url, headers=headers, timeout=30).status_code == 200
    except requests.RequestException as e:
        logger.warning("HTTP GET %s failed: %s", url, e)
        return False
