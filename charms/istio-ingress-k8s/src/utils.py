#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility functions for istio-ingress charm.

This module contains normalization, deduplication, and helper functions used by the charm.
Functions here are source-agnostic and work on normalized data structures.
"""
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple, TypedDict

from canonical_service_mesh.models import (
    BackendRef,
    GRPCMethodMatch,
    GRPCRouteMatch,
    HTTPPathMatch,
    HTTPRouteMatch,
)
from charmlibs.interfaces.istio_ingress_route import (
    PathModifier,
    PathModifierType,
    RequestRedirectFilter,
    RequestRedirectSpec,
    URLRewriteFilter,
    URLRewriteSpec,
    to_gateway_protocol,
)
from ops import EventBase

HTTPRouteFilter = URLRewriteFilter | RequestRedirectFilter
GRPCRouteFilter = RequestRedirectFilter

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================
INGRESS_AUTHENTICATED_NAME = "ingress"
INGRESS_UNAUTHENTICATED_NAME = "ingress-unauthenticated"
ISTIO_INGRESS_ROUTE_AUTHENTICATED_NAME = "istio-ingress-route"
ISTIO_INGRESS_ROUTE_UNAUTHENTICATED_NAME = "istio-ingress-route-unauthenticated"


# ============================================================================
# Exception Classes
# ============================================================================
class DataValidationError(RuntimeError):
    """Raised when data validation fails on IPU relation data."""


class DisabledCertHandler:
    """A mock CertHandler class that mimics being unavailable."""

    available: bool = False
    server_cert = None
    private_key = None


class RefreshCerts(EventBase):
    """Event raised when the charm wants the certs to be refreshed."""


# ============================================================================
# Adapter Schemas
# ============================================================================
class RouteInfo(TypedDict):
    """Class to hold route information."""

    service_name: str
    namespace: str
    port: int
    strip_prefix: bool
    prefix: Optional[str]


class GatewayListener(TypedDict):
    """Normalized Gateway listener data structure."""

    port: int
    gateway_protocol: str
    tls_secret_name: Optional[str]
    source_app: str


class HTTPRoute(TypedDict):
    """Normalized HTTPRoute data structure.

    All fields use charm models from models.py (K8s Gateway API format).
    """

    name: str
    listener_port: int
    listener_protocol: str  # Gateway protocol ("HTTP" or "HTTPS")
    namespace: str
    source_app: str
    source_relation: str
    matches: List[HTTPRouteMatch]
    backend_refs: List[BackendRef]
    filters: List[HTTPRouteFilter]


class GRPCRoute(TypedDict):
    """Normalized GRPCRoute data structure.

    All fields use charm models from models.py (K8s Gateway API format).
    """

    name: str
    listener_port: int
    listener_protocol: str  # Gateway protocol ("HTTP" or "HTTPS")
    namespace: str
    source_app: str
    source_relation: str
    matches: List[GRPCRouteMatch]
    backend_refs: List[BackendRef]
    filters: List[GRPCRouteFilter]


# ============================================================================
# Adapters
# ============================================================================
def normalize_ipa_listeners(tls_secret_name: Optional[str]) -> List[GatewayListener]:
    """Normalize IPA listeners to common format.

    IPA always uses standard ports: 80 for HTTP, 443 for HTTPS.

    Args:
        tls_secret_name: Name of TLS secret if TLS is enabled

    Returns:
        List of normalized listeners (http-80, and https-443 if TLS enabled)
    """
    listeners: List[GatewayListener] = [
        GatewayListener(
            port=80,
            gateway_protocol="HTTP",
            tls_secret_name=None,
            source_app="ipa",
        )
    ]

    if tls_secret_name:
        listeners.append(
            GatewayListener(
                port=443,
                gateway_protocol="HTTPS",
                tls_secret_name=tls_secret_name,
                source_app="ipa",
            )
        )

    return listeners


def normalize_istio_ingress_route_listeners(
    istio_ingress_route_configs: dict, tls_secret_name: Optional[str]
) -> List[GatewayListener]:
    """Normalize istio-ingress-route listeners to common format.

    Args:
        istio_ingress_route_configs: Dict mapping (app_name, relation_name) to config data
        tls_secret_name: Name of TLS secret if TLS is enabled

    Returns:
        List of normalized listeners
    """
    listeners: List[GatewayListener] = []

    for (app_name, relation_name), config_data in istio_ingress_route_configs.items():
        config = config_data["config"]
        if not config:
            continue

        for listener in config.listeners:
            # Apply TLS upgrade
            gateway_protocol = to_gateway_protocol(
                listener.protocol, tls_enabled=tls_secret_name is not None
            )

            listeners.append(
                GatewayListener(
                    port=listener.port,
                    gateway_protocol=gateway_protocol,
                    tls_secret_name=tls_secret_name if gateway_protocol == "HTTPS" else None,
                    source_app=app_name,
                )
            )

    return listeners


def _create_http_redirect_route(
    service_name: str,
    namespace: str,
    prefix: str,
    source_app: str,
    source_relation: str,
    ingress_app_name: str,
) -> HTTPRoute:
    """Create an HTTP->HTTPS redirect route between the standard http-80 and https-443 listeners.

    Args:
        service_name: Name of the backend service
        namespace: Namespace of the route
        prefix: URL path prefix
        source_app: Source application name
        source_relation: Source relation name
        ingress_app_name: Name of the ingress charm app

    Returns:
        HTTPRoute with RequestRedirect filter
    """
    section_name = "http-80"
    route_name = f"{service_name}-httproute-{section_name}-{ingress_app_name}"

    filters: List[HTTPRouteFilter] = []
    filters.append(
        RequestRedirectFilter(
            requestRedirect=RequestRedirectSpec(scheme="https", statusCode=301)
        )  # https redirection without port spec will always redirect to the standard 443 port.
    )

    return HTTPRoute(
        name=route_name,
        listener_port=80,
        listener_protocol="HTTP",
        namespace=namespace,
        source_app=source_app,
        source_relation=source_relation,
        matches=[
            HTTPRouteMatch(
                path=HTTPPathMatch(type="PathPrefix", value=prefix)
            )
        ],
        backend_refs=[],  # No backends for redirect routes
        filters=filters,
    )


def normalize_ipa_routes(
    application_route_data: dict, is_tls_enabled: bool, ingress_app_name: str
) -> List[HTTPRoute]:
    """Normalize IPA routes to common format with complete conversion to charm models.

    Converts IPA raw route data to fully normalized K8s Gateway API format using charm Pydantic models.
    IPA routes are always HTTPRoutes on standard ports (80/443).

    Args:
        application_route_data: Dict mapping (app_name, relation_name) to route data
        is_tls_enabled: Whether TLS is enabled
        ingress_app_name: Name of the ingress charm app (used in route naming)

    Returns:
        List of normalized HTTP routes with charm models (HTTPRouteMatch, BackendRef, HTTPRouteFilter)
    """
    routes: List[HTTPRoute] = []

    for (app_name, relation_name), route_data in application_route_data.items():
        for route in route_data["routes"]:
            # Common data for all routes
            matches = [
                HTTPRouteMatch(
                    path=HTTPPathMatch(type="PathPrefix", value=route["prefix"])
                )
            ]
            backend_refs = [
                BackendRef(
                    name=route["service_name"],
                    port=route["port"],
                    namespace=route["namespace"],
                )
            ]

            # Build filters for URLRewrite if needed
            filters: List[HTTPRouteFilter] = []
            if route["strip_prefix"]:
                filters.append(
                    URLRewriteFilter(
                        urlRewrite=URLRewriteSpec(
                            path=PathModifier(
                                type=PathModifierType.ReplacePrefixMatch,
                                value="/"
                            )
                        )
                    )
                )

            if is_tls_enabled:
                # Create HTTP->HTTPS redirect route
                routes.append(
                    _create_http_redirect_route(
                        service_name=route["service_name"],
                        namespace=route["namespace"],
                        prefix=route["prefix"],
                        source_app=app_name,
                        source_relation=relation_name,
                        ingress_app_name=ingress_app_name,
                    )
                )

                # Create HTTPS route with backends
                section_name = "https-443"
                route_name = f"{route['service_name']}-httproute-{section_name}-{ingress_app_name}"
                routes.append(
                    HTTPRoute(
                        name=route_name,
                        listener_port=443,
                        listener_protocol="HTTPS",
                        namespace=route["namespace"],
                        source_app=app_name,
                        source_relation=relation_name,
                        matches=matches,
                        backend_refs=backend_refs,
                        filters=filters,
                    )
                )
            else:
                # Create HTTP route
                section_name = "http-80"
                route_name = f"{route['service_name']}-httproute-{section_name}-{ingress_app_name}"
                routes.append(
                    HTTPRoute(
                        name=route_name,
                        listener_port=80,
                        listener_protocol="HTTP",
                        namespace=route["namespace"],
                        source_app=app_name,
                        source_relation=relation_name,
                        matches=matches,
                        backend_refs=backend_refs,
                        filters=filters,
                    )
                )

    return routes


def normalize_istio_ingress_route_http_routes(
    istio_ingress_route_configs: dict, is_tls_enabled: bool, ingress_app_name: str
) -> List[HTTPRoute]:
    """Normalize istio-ingress-route HTTP routes to common format with complete conversion to charm models.

    Converts library models (from istio_ingress_route relation) to charm Pydantic models (from models.py).
    This ensures complete normalization to K8s Gateway API format.

    Args:
        istio_ingress_route_configs: Dict mapping (app_name, relation_name) to config data
        is_tls_enabled: Whether TLS is enabled
        ingress_app_name: Name of the ingress charm app (used in route naming)

    Returns:
        List of normalized HTTP routes with charm models (HTTPRouteMatch, BackendRef, HTTPRouteFilter)
    """
    routes: List[HTTPRoute] = []

    for (app_name, relation_name), config_data in istio_ingress_route_configs.items():
        config = config_data["config"]
        if not config:
            continue

        for http_route in config.http_routes:
            # Determine Gateway protocol for this listener
            gateway_protocol = to_gateway_protocol(
                http_route.listener.protocol, tls_enabled=is_tls_enabled
            )

            # Convert library HTTPRouteMatch models to charm models
            matches = []
            for lib_match in http_route.matches or []:
                if lib_match.path:
                    matches.append(
                        HTTPRouteMatch(
                            path=HTTPPathMatch(
                                type=lib_match.path.type,
                                value=lib_match.path.value,
                            )
                        )
                    )

            # Convert library BackendRef models to charm models
            backend_refs = []
            for lib_backend in http_route.backends or []:
                backend_refs.append(
                    BackendRef(
                        name=lib_backend.service,
                        port=lib_backend.port,
                        namespace=config.model,
                    )
                )

            # Library filters are directly compatible - no conversion needed!
            filters = list(http_route.filters) if http_route.filters else []

            # Derive route name
            # Format: {app_name}-{http_route.name}-httproute-{section_name}-{ingress_app_name}
            # Example: myapp-api-route-httproute-http-8080-istio-ingress-k8s
            section_name = f"{gateway_protocol.lower()}-{http_route.listener.port}"
            route_name = f"{app_name}-{http_route.name}-httproute-{section_name}-{ingress_app_name}"

            routes.append(
                HTTPRoute(
                    name=route_name,
                    listener_port=http_route.listener.port,
                    listener_protocol=gateway_protocol,
                    namespace=config.model,
                    source_app=app_name,
                    source_relation=relation_name,
                    matches=matches,
                    backend_refs=backend_refs,
                    filters=filters,
                )
            )

    return routes


def normalize_istio_ingress_route_grpc_routes(
    istio_ingress_route_configs: dict, is_tls_enabled: bool, ingress_app_name: str
) -> List[GRPCRoute]:
    """Normalize istio-ingress-route gRPC routes to common format with complete conversion to charm models.

    Converts library models (from istio_ingress_route relation) to charm Pydantic models (from models.py).
    This ensures complete normalization to K8s Gateway API format.

    Args:
        istio_ingress_route_configs: Dict mapping (app_name, relation_name) to config data
        is_tls_enabled: Whether TLS is enabled
        ingress_app_name: Name of the ingress charm app (used in route naming)

    Returns:
        List of normalized gRPC routes with charm models (GRPCRouteMatch, BackendRef, HTTPRouteFilter)
    """
    routes: List[GRPCRoute] = []

    for (app_name, relation_name), config_data in istio_ingress_route_configs.items():
        config = config_data["config"]
        if not config:
            continue

        for grpc_route in config.grpc_routes:
            # Determine Gateway protocol for this listener
            gateway_protocol = to_gateway_protocol(
                grpc_route.listener.protocol, tls_enabled=is_tls_enabled
            )

            # Convert library GRPCRouteMatch models to charm models
            matches = []
            for lib_match in grpc_route.matches or []:
                if lib_match.method:
                    matches.append(
                        GRPCRouteMatch(
                            method=GRPCMethodMatch(
                                service=lib_match.method.service,
                                method=lib_match.method.method,
                            )
                        )
                    )

            # Convert library BackendRef models to charm models
            backend_refs = []
            for lib_backend in grpc_route.backends or []:
                backend_refs.append(
                    BackendRef(
                        name=lib_backend.service,
                        port=lib_backend.port,
                        namespace=config.model,
                    )
                )

            # GRPCRouteFilter not yet implemented - leave empty for now
            filters = []
            # TODO: When GRPCRouteFilter is implemented, use:
            # filters = list(grpc_route.filters) if grpc_route.filters else []

            # Derive route name
            # Format: {app_name}-{grpc_route.name}-grpcroute-{section_name}-{ingress_app_name}
            # Example: myapp-user-service-grpcroute-http-9090-istio-ingress-k8s
            section_name = f"{gateway_protocol.lower()}-{grpc_route.listener.port}"
            route_name = f"{app_name}-{grpc_route.name}-grpcroute-{section_name}-{ingress_app_name}"

            routes.append(
                GRPCRoute(
                    name=route_name,
                    listener_port=grpc_route.listener.port,
                    listener_protocol=gateway_protocol,
                    namespace=config.model,
                    source_app=app_name,
                    source_relation=relation_name,
                    matches=matches,
                    backend_refs=backend_refs,
                    filters=filters,
                )
            )

    return routes


# ============================================================================
# Generic Processing Functions (work on normalized data)
# ============================================================================
def deduplicate_listeners(all_listeners: List[GatewayListener]) -> List[GatewayListener]:
    """Merge listeners by deduplicating on (port, gateway_protocol).

    Keeps the first occurrence of each unique (port, protocol) combination.
    This handles cases where both IPA and istio-ingress-route request the same port.

    For example, given input:
        [
            _GatewayListener(port=80, gateway_protocol="HTTP", source_app="ipa", ...),
            _GatewayListener(port=443, gateway_protocol="HTTPS", source_app="ipa", ...),
            _GatewayListener(port=80, gateway_protocol="HTTP", source_app="app1", ...),  # Duplicate
            _GatewayListener(port=8080, gateway_protocol="HTTP", source_app="app2", ...),
        ]

    This function would return:
        [
            _GatewayListener(port=80, gateway_protocol="HTTP", source_app="ipa", ...),    # First wins
            _GatewayListener(port=443, gateway_protocol="HTTPS", source_app="ipa", ...),
            _GatewayListener(port=8080, gateway_protocol="HTTP", source_app="app2", ...),
        ]

    Args:
        all_listeners: Combined list of all normalized listeners from all sources

    Returns:
        List of unique listeners (first occurrence wins for each unique port/protocol pair)
    """
    seen: Dict[Tuple[int, str], GatewayListener] = {}

    for listener in all_listeners:
        key = (listener["port"], listener["gateway_protocol"])
        if key not in seen:
            seen[key] = listener

    return list(seen.values())


def deduplicate_http_routes(
    all_http_routes: List[HTTPRoute],
) -> Tuple[List[HTTPRoute], Set[Tuple[str, str]]]:
    """Deduplicate HTTP routes by finding conflicts on (listener_port, listener_protocol, path).

    Routes from the same app can share the same path. Routes from different apps cannot.
    When a conflict is detected, ALL routes from ALL conflicting apps are removed.

    What constitutes a conflict:
    - Two or more routes from DIFFERENT apps requesting the same path on the same listener
    - Listener is identified by (port, protocol) combination
    - Path must match exactly

    Non-conflict examples:
    - App A: path="/api" on HTTP:80
      App A: path="/api" on HTTP:80  (same app = OK, multiple routes allowed)
    - App A: path="/api" on HTTP:80
      App B: path="/users" on HTTP:80  (different paths = OK)
    - App A: path="/api" on HTTP:80
      App B: path="/api" on HTTP:8080  (different listeners = OK)

    For example, given input:
        [
            _HTTPRoute(name="r0", listener_port=80, listener_protocol="HTTP",
                      path="/api", source_app="app0", source_relation="ingress"),  # <-- Duplicate /api
            _HTTPRoute(name="r1", listener_port=80, listener_protocol="HTTP",
                      path="/users", source_app="app1", source_relation="ingress"),
            _HTTPRoute(name="r2", listener_port=80, listener_protocol="HTTP",
                      path="/api", source_app="app2", source_relation="istio-ingress-route"),  # <-- Duplicate /api
            _HTTPRoute(name="r3", listener_port=443, listener_protocol="HTTPS",
                      path="/admin", source_app="app3", source_relation="ingress"),  # <-- Duplicate /admin
            _HTTPRoute(name="r4", listener_port=443, listener_protocol="HTTPS",
                      path="/admin", source_app="app4", source_relation="ingress"),  # <-- Duplicate /admin
        ]

    This function would return:
        (
            [
                _HTTPRoute(...path="/users"...),  # No conflict
            ],
            {("app0", "ingress"), ("app2", "istio-ingress-route"), ("app3", "ingress"), ("app4", "ingress")},
            True  # has_conflicts
        )

    The routes for /api on HTTP:80 and /admin on HTTPS:443 would be removed because multiple
    apps requested them. The /users route would remain because only one app requested it.

    Note: This function does NOT modify the original data structures. Use clear_conflicting_routes()
    to apply the clearing to the original application_route_data and istio_ingress_route_configs.

    TODO: The caller should set BlockedStatus when has_conflicts is True, since this is a
    user-actionable error. See: https://github.com/canonical/istio-ingress-k8s-operator/issues/57

    Args:
        all_http_routes: Combined list of all normalized HTTP routes from all sources

    Returns:
        Tuple of (valid_routes, apps_to_clear, has_conflicts) where:
        - valid_routes: List of non-conflicting routes
        - apps_to_clear: Set of (app_name, relation_name) tuples that have conflicts
        - has_conflicts: True if any conflicts were detected (caller should set BlockedStatus)
    """
    # Group routes by (listener_port, listener_protocol, path)
    # Extract path from first match in matches list
    route_groups: Dict[Tuple[int, str, str], List[HTTPRoute]] = defaultdict(list)

    for route in all_http_routes:
        # Extract path from first HTTPRouteMatch
        path = route["matches"][0].path.value if route["matches"] else "/"
        key = (route["listener_port"], route["listener_protocol"], path)
        route_groups[key].append(route)

    valid_routes: List[HTTPRoute] = []
    apps_to_clear: Set[Tuple[str, str]] = set()

    for key, routes in route_groups.items():
        # Get unique apps requesting this route
        unique_apps = {(r["source_app"], r["source_relation"]) for r in routes}

        if len(unique_apps) > 1:
            # Conflict detected - multiple apps want the same route
            listener_port, listener_protocol, path = key
            logger.error(
                f"Route conflict detected: Multiple applications requesting "
                f"{listener_protocol}:{listener_port}{path}. "
                f"Conflicting apps: {', '.join(f'{app}/{rel}' for app, rel in unique_apps)}. "
                f"No route will be created for this path."
            )
            # Mark all conflicting apps for clearing
            apps_to_clear.update(unique_apps)
        else:
            # No conflict - keep all routes (may be multiple from same app)
            valid_routes.extend(routes)

    return valid_routes, apps_to_clear


def deduplicate_grpc_routes(
    all_grpc_routes: List[GRPCRoute],
) -> Tuple[List[GRPCRoute], Set[Tuple[str, str]]]:
    """Deduplicate gRPC routes by finding conflicts on (listener_port, listener_protocol, grpc_path).

    Routes from the same app can share the same gRPC path. Routes from different apps cannot.
    When a conflict is detected, ALL routes from ALL conflicting apps are removed.

    What constitutes a conflict:
    - Two or more routes from DIFFERENT apps requesting the same gRPC method on the same listener
    - Listener is identified by (port, protocol) combination
    - gRPC path format: /service/method or /service/*

    Non-conflict examples:
    - App A: /UserService/GetUser on HTTP:8080
      App A: /UserService/GetUser on HTTP:8080  (same app = OK)
    - App A: /UserService/GetUser on HTTP:8080
      App B: /OrderService/GetOrder on HTTP:8080  (different services = OK)
    - App A: /UserService/GetUser on HTTP:8080
      App B: /UserService/GetUser on HTTP:9090  (different listeners = OK)

    Important: HTTP and gRPC routes on the same port CAN coexist because they use different
    match criteria (HTTP uses path matching, gRPC uses method matching). This function only
    checks for conflicts between gRPC routes.

    For example, given input:
        [
            _GRPCRoute(name="r0", listener_port=8080, listener_protocol="HTTP",
                      grpc_path="/UserService/GetUser", source_app="app0", ...),  # <-- Duplicate
            _GRPCRoute(name="r1", listener_port=8080, listener_protocol="HTTP",
                      grpc_path="/OrderService/GetOrder", source_app="app1", ...),
            _GRPCRoute(name="r2", listener_port=8080, listener_protocol="HTTP",
                      grpc_path="/UserService/GetUser", source_app="app2", ...),  # <-- Duplicate
        ]

    This function would return:
        (
            [
                _GRPCRoute(...grpc_path="/OrderService/GetOrder"...),  # No conflict
            ],
            {("app0", "istio-ingress-route"), ("app2", "istio-ingress-route")},
            True  # has_conflicts
        )

    Note: This function does NOT modify the original data structures. Use clear_conflicting_routes()
    to apply the clearing to the original istio_ingress_route_configs.

    TODO: The caller should set BlockedStatus when has_conflicts is True, since this is a
    user-actionable error. See: https://github.com/canonical/istio-ingress-k8s-operator/issues/57

    Args:
        all_grpc_routes: Combined list of all normalized gRPC routes from all sources

    Returns:
        Tuple of (valid_routes, apps_to_clear, has_conflicts) where:
        - valid_routes: List of non-conflicting routes
        - apps_to_clear: Set of (app_name, relation_name) tuples that have conflicts
        - has_conflicts: True if any conflicts were detected (caller should set BlockedStatus)
    """
    # Group routes by (listener_port, listener_protocol, grpc_path)
    # Extract grpc_path from first match in matches list
    route_groups: Dict[Tuple[int, str, str], List[GRPCRoute]] = defaultdict(list)

    for route in all_grpc_routes:
        # Extract gRPC path from first GRPCRouteMatch
        if route["matches"] and route["matches"][0].method:
            method_match = route["matches"][0].method
            service = method_match.service or ""
            method = method_match.method or "*"
            grpc_path = f"/{service}/{method}"
        else:
            grpc_path = "/*"

        key = (route["listener_port"], route["listener_protocol"], grpc_path)
        route_groups[key].append(route)

    valid_routes: List[GRPCRoute] = []
    apps_to_clear: Set[Tuple[str, str]] = set()

    for key, routes in route_groups.items():
        # Get unique apps requesting this route
        unique_apps = {(r["source_app"], r["source_relation"]) for r in routes}

        if len(unique_apps) > 1:
            # Conflict detected - multiple apps want the same route
            listener_port, listener_protocol, grpc_path = key
            logger.error(
                f"gRPC route conflict detected: Multiple applications requesting "
                f"{listener_protocol}:{listener_port}{grpc_path}. "
                f"Conflicting apps: {', '.join(f'{app}/{rel}' for app, rel in unique_apps)}. "
                f"No route will be created for this path."
            )
            # Mark all conflicting apps for clearing
            apps_to_clear.update(unique_apps)
        else:
            # No conflict - keep all routes (may be multiple from same app)
            valid_routes.extend(routes)

    return valid_routes, apps_to_clear


def clear_conflicting_routes(
    application_route_data: Dict,
    istio_ingress_route_configs: Dict,
    apps_to_clear: Set[Tuple[str, str]],
) -> None:
    """Clear routes for applications that have conflicts, modifying the input in place.

    This function applies the conflict resolution determined by deduplicate_http_routes()
    and deduplicate_grpc_routes() to the original data structures. For any app that has
    ANY conflicting route, ALL of its routes are removed.

    For example, given:
        apps_to_clear = {("app0", "ingress"), ("app2", "istio-ingress-route")}

        application_route_data = {
            ("app0", "ingress"): {"handler": ..., "routes": [{"prefix": "/api"}]},
            ("app1", "ingress"): {"handler": ..., "routes": [{"prefix": "/users"}]},
        }

        istio_ingress_route_configs = {
            ("app2", "istio-ingress-route"): {"handler": ..., "config": IstioIngressRouteConfig(...)},
            ("app3", "istio-ingress-route"): {"handler": ..., "config": IstioIngressRouteConfig(...)},
        }

    After calling this function:
        application_route_data = {
            ("app0", "ingress"): {"handler": ..., "routes": []},  # <-- Cleared
            ("app1", "ingress"): {"handler": ..., "routes": [{"prefix": "/users"}]},
        }

        istio_ingress_route_configs = {
            ("app2", "istio-ingress-route"): {"handler": ..., "config": IstioIngressRouteConfig(
                http_routes=[], grpc_routes=[]  # <-- Cleared
            )},
            ("app3", "istio-ingress-route"): {"handler": ..., "config": IstioIngressRouteConfig(...)},
        }

    Note: This function does not remove keys from the data structures because we still need
    those later in case we need to nullify what we've previously sent via the relation.

    Side effects: Modifies application_route_data and istio_ingress_route_configs in place.

    Args:
        application_route_data: IPA route data dict (modified in place)
        istio_ingress_route_configs: istio-ingress-route config data dict (modified in place)
        apps_to_clear: Set of (app_name, relation_name) tuples to clear
    """
    for app_name, relation_name in apps_to_clear:
        app_key = (app_name, relation_name)

        # Clear from IPA routes
        if app_key in application_route_data:
            application_route_data[app_key]["routes"] = []
            logger.debug(f"Cleared IPA routes for {app_name}/{relation_name} due to conflict")

        # Clear from istio-ingress-route configs
        if app_key in istio_ingress_route_configs:
            config = istio_ingress_route_configs[app_key]["config"]
            if config:
                config.http_routes = []
                config.grpc_routes = []
                logger.debug(
                    f"Cleared istio-ingress-route routes for {app_name}/{relation_name} due to conflict"
                )


# ============================================================================
# Helper Functions
# ============================================================================
def get_unauthenticated_paths(application_route_data):
    """Return a list of the paths requested through the Gateway on the unauthenticated ingress."""
    unauthenticated_paths = []
    for (_, endpoint), route_data in application_route_data.items():
        if endpoint == INGRESS_UNAUTHENTICATED_NAME:
            for route in route_data["routes"]:
                # Ensure subpaths are also unauthenticated by appending /*
                prefix = route["prefix"].rstrip("/")
                unauthenticated_paths.extend([prefix, prefix + "/*"])
    return unauthenticated_paths


def _extract_http_unauthenticated_paths(http_routes):
    """Extract HTTP paths that should be unauthenticated.

    Args:
        http_routes: List of HTTP route configurations

    Returns:
        List of HTTP path strings
    """
    paths = []
    for http_route in http_routes:
        for match in http_route.matches or []:
            if match.path:
                # Ensure subpaths are also unauthenticated by appending /*
                path = match.path.value.rstrip("/")
                paths.extend([path, path + "/*"])
    return paths


def _extract_grpc_unauthenticated_paths(grpc_routes):
    """Extract gRPC paths that should be unauthenticated.

    Args:
        grpc_routes: List of gRPC route configurations

    Returns:
        List of gRPC path strings in format /service/method
    """
    paths = []
    for grpc_route in grpc_routes:
        for match in grpc_route.matches or []:
            if match.method:
                service = match.method.service
                method = match.method.method
                if method:
                    # Specific method: /service/method
                    paths.append(f"/{service}/{method}")
                else:
                    # All methods on service: /service/*
                    paths.append(f"/{service}/*")
    return paths


def get_unauthenticated_paths_from_istio_ingress_route_configs(istio_ingress_route_configs):
    """Return a list of paths from istio-ingress-route-unauthenticated configs.

    Args:
        istio_ingress_route_configs: Dict mapping (app_name, relation_name) to {"handler": ..., "config": ...}

    Returns:
        List of path strings that should be unauthenticated (HTTP paths and gRPC fully-qualified names)
    """
    unauthenticated_paths = []
    for (_, relation_name), config_data in istio_ingress_route_configs.items():
        if relation_name == ISTIO_INGRESS_ROUTE_UNAUTHENTICATED_NAME:
            config = config_data["config"]
            if not config:
                continue

            # Extract paths from HTTP routes
            unauthenticated_paths.extend(_extract_http_unauthenticated_paths(config.http_routes))

            # Extract fully-qualified gRPC paths from gRPC routes
            unauthenticated_paths.extend(_extract_grpc_unauthenticated_paths(config.grpc_routes))

    return unauthenticated_paths


def get_relation_by_name_and_app(relations, remote_app_name):
    """Return the relation object associated with a given remote app."""
    for rel in relations:
        if rel.app.name == remote_app_name:
            return rel
    raise KeyError(f"Could not find relation with remote_app_name={remote_app_name}")


