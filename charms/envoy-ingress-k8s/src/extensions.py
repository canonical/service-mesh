# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Config-driven L4/L7 routes, allowlist and HTTP/3 policy for the ingress charm.

Pure builders: they take parsed config and return plain dicts / lightkube
resources, so they are unit-testable without a cluster.
"""

import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Optional

from lightkube.generic_resource import create_namespaced_resource
from lightkube.models.meta_v1 import ObjectMeta

# TCPRoute and UDPRoute are Gateway API kinds; the controller
# charm bundles their CRDs.
TCPRoute = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "TCPRoute", "tcproutes"
)
UDPRoute = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "UDPRoute", "udproutes"
)
ClientTrafficPolicy = create_namespaced_resource(
    "gateway.envoyproxy.io", "v1alpha1", "ClientTrafficPolicy", "clienttrafficpolicies"
)

PROTOCOLS = ("http", "tcp", "tls-terminate", "udp")
_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class ConfigError(ValueError):
    """Raised when a charm config option is malformed."""


@dataclass(frozen=True)
class ExtraRoute:
    """One user-declared route, backed by a Kubernetes Service."""

    name: str
    protocol: str
    service: str
    namespace: str
    service_port: int
    port: Optional[int] = None  # Gateway listener port (L4 only)
    hostnames: list = field(default_factory=list)
    path_prefix: str = "/"
    strip_prefix: bool = False

    @property
    def listener_name(self) -> str:
        """Gateway listener name shared by the listener and the route's sectionName."""
        return f"{self.protocol}-{self.port}"


def parse_cidrs(value: str) -> list:
    """Parse a comma/space separated CIDR list; bare IPs become /32 or /128."""
    cidrs = []
    for item in re.split(r"[,\s]+", (value or "").strip()):
        if not item:
            continue
        try:
            cidrs.append(str(ipaddress.ip_network(item, strict=False)))
        except ValueError as e:
            raise ConfigError(f"invalid CIDR {item!r}") from e
    return cidrs


def parse_ips(value: str) -> list:
    """Parse a comma/space separated list of IP addresses."""
    ips = []
    for item in re.split(r"[,\s]+", (value or "").strip()):
        if not item:
            continue
        try:
            ips.append(str(ipaddress.ip_address(item)))
        except ValueError as e:
            raise ConfigError(f"invalid IP address {item!r}") from e
    return ips


def parse_extra_routes(value: str) -> list:
    """Parse and validate the JSON ``extra-routes`` option."""
    if not (value or "").strip():
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as e:
        raise ConfigError(f"extra-routes is not valid JSON: {e}") from e
    if not isinstance(raw, list):
        raise ConfigError("extra-routes must be a JSON list")

    routes, names, listeners = [], set(), {}
    for i, item in enumerate(raw):
        route = _build_route(i, item)
        if route.name in names:
            raise ConfigError(f"duplicate route name {route.name!r}")
        names.add(route.name)
        _validate_route(i, route, listeners)
        routes.append(route)
    return routes


def _build_route(i: int, item) -> ExtraRoute:
    if not isinstance(item, dict):
        raise ConfigError(f"extra-routes[{i}] must be an object")
    try:
        return ExtraRoute(
            name=str(item["name"]),
            protocol=str(item.get("protocol", "http")),
            service=str(item["service"]),
            namespace=str(item["namespace"]),
            service_port=int(item["service_port"]),
            port=int(item["port"]) if item.get("port") is not None else None,
            hostnames=[str(h) for h in item.get("hostnames", [])],
            path_prefix=str(item.get("path_prefix", "/")),
            strip_prefix=bool(item.get("strip_prefix", False)),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"extra-routes[{i}] is incomplete or malformed: {e!r}") from e


def _validate_route(i: int, route: ExtraRoute, listeners: dict) -> None:
    if not _NAME_RE.match(route.name):
        raise ConfigError(f"extra-routes[{i}].name must be a DNS label")
    if route.protocol not in PROTOCOLS:
        raise ConfigError(f"extra-routes[{i}].protocol must be one of {PROTOCOLS}")
    if not 1 <= route.service_port <= 65535:
        raise ConfigError(f"extra-routes[{i}].service_port out of range")
    if not route.path_prefix.startswith("/"):
        raise ConfigError(f"extra-routes[{i}].path_prefix must start with '/'")
    if route.protocol == "http":
        return
    if route.port is None or not 1 <= route.port <= 65535:
        raise ConfigError(f"extra-routes[{i}].port is required for {route.protocol}")
    if route.port in (80, 443) and route.protocol != "udp":
        raise ConfigError(f"extra-routes[{i}].port {route.port} is reserved for HTTP(S)")
    key = (route.protocol == "udp", route.port)
    if key in listeners:
        raise ConfigError(
            f"extra-routes[{i}] reuses {route.protocol}/{route.port} "
            f"already used by {listeners[key]!r}"
        )
    listeners[key] = route.name


def l4_listeners(routes: list, tls_secret: Optional[dict]) -> list:
    """Gateway listeners for the L4 routes; tls-terminate needs ``tls_secret``."""
    listeners = []
    for r in routes:
        if r.protocol == "http":
            continue
        listener = {
            "name": r.listener_name,
            "port": r.port,
            "allowedRoutes": {"namespaces": {"from": "All"}},
        }
        if r.protocol == "tcp":
            listener["protocol"] = "TCP"
        elif r.protocol == "udp":
            listener["protocol"] = "UDP"
        else:
            if not tls_secret:
                continue
            listener["protocol"] = "TLS"
            listener["tls"] = {"mode": "Terminate", "certificateRefs": [tls_secret]}
        listeners.append(listener)
    return listeners


def l4_route(route: ExtraRoute, gateway: str, gateway_namespace: str):
    """Build the TCPRoute/UDPRoute for an L4 ExtraRoute."""
    kind = UDPRoute if route.protocol == "udp" else TCPRoute
    spec = {
        "parentRefs": [
            {"name": gateway, "namespace": gateway_namespace, "sectionName": route.listener_name}
        ],
        "rules": [{"backendRefs": [{"name": route.service, "port": route.service_port}]}],
    }
    return kind(metadata=ObjectMeta(name=route.name, namespace=route.namespace), spec=spec)


def http_rule(route: ExtraRoute) -> dict:
    """HTTPRoute rule for an http ExtraRoute."""
    rule = {
        "matches": [{"path": {"type": "PathPrefix", "value": route.path_prefix}}],
        "backendRefs": [
            {"name": route.service, "port": route.service_port, "namespace": route.namespace}
        ],
    }
    if route.strip_prefix and route.path_prefix != "/":
        rule["filters"] = [
            {
                "type": "URLRewrite",
                "urlRewrite": {"path": {"type": "ReplacePrefixMatch", "replacePrefixMatch": "/"}},
            }
        ]
    return rule


def authorization(cidrs: list) -> Optional[dict]:
    """SecurityPolicy ``authorization`` block allowing only the given client CIDRs."""
    if not cidrs:
        return None
    return {
        "defaultAction": "Deny",
        "rules": [
            {"name": "allowed-clients", "action": "Allow", "principal": {"clientCIDRs": cidrs}}
        ],
    }


def http3_policy(gateway: str, namespace: str):
    """ClientTrafficPolicy enabling HTTP/3 (QUIC) on every HTTPS listener of the Gateway."""
    return ClientTrafficPolicy(
        metadata=ObjectMeta(name=f"{gateway}-http3", namespace=namespace),
        spec={
            "targetRefs": [
                {"group": "gateway.networking.k8s.io", "kind": "Gateway", "name": gateway}
            ],
            "http3": {},
        },
    )
