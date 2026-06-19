#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Istio Ingress Charm."""
import ipaddress
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple, cast
from urllib.parse import urlparse

from canonical_service_mesh.enums import Action
from canonical_service_mesh.interfaces.istio_ingress_config import (
    DEFAULT_HEADERS_TO_DOWNSTREAM_ON_ALLOW,
    DEFAULT_HEADERS_TO_DOWNSTREAM_ON_DENY,
    DEFAULT_HEADERS_TO_UPSTREAM_ON_ALLOW,
    DEFAULT_INCLUDE_HEADERS_IN_CHECK,
    IngressConfigProvider,
)
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    PolicyResourceManager,
    create_charm_default_labels,
)
from canonical_service_mesh.k8s.types.istio import AuthorizationPolicy
from canonical_service_mesh.models import (
    AllowedRoutes,
    GatewayTLSConfig,
    GRPCRouteResource,
    GRPCRouteResourceSpec,
    GRPCRouteRule,
    HTTPRouteResource,
    HTTPRouteResourceSpec,
    HTTPRouteRule,
    IstioGatewayResource,
    IstioGatewaySpec,
    Listener,
    Metadata,
    ParentRef,
    SecretObjectReference,
)
from canonical_service_mesh.models.istio import (
    AuthorizationPolicySpec,
    ClaimToHeader,
    Condition,
    From,
    FromHeader,
    JWTRule,
    Operation,
    PolicyTargetReference,
    Provider,
    RequestAuthenticationSpec,
    Rule,
    Source,
    To,
    WorkloadSelector,
)
from canonical_service_mesh.utils import (
    generate_telemetry_labels,
    get_peer_identity_for_juju_application,
)
from charmlibs.interfaces.gateway_metadata import GatewayMetadata, GatewayMetadataProvider
from charmlibs.interfaces.istio_ingress_route import IstioIngressRouteProvider
from charmlibs.interfaces.istio_request_auth import IstioRequestAuthProvider
from charmlibs.interfaces.service_mesh import MeshType
from charms.oauth2_proxy_k8s.v0.forward_auth import ForwardAuthRequirer, ForwardAuthRequirerConfig
from charms.observability_libs.v1.cert_handler import CertHandler
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider as IPAv2
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from lightkube.models.autoscaling_v2 import (
    CrossVersionObjectReference,
    HorizontalPodAutoscalerSpec,
)
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.autoscaling_v2 import HorizontalPodAutoscaler
from lightkube.resources.core_v1 import Secret, Service
from lightkube.types import PatchType
from ops import BlockedStatus, CollectStatusEvent, main
from ops.charm import CharmBase
from ops.model import ActiveStatus, MaintenanceStatus
from ops.pebble import ChangeError, Layer

from utils import (
    INGRESS_AUTHENTICATED_NAME,
    INGRESS_UNAUTHENTICATED_NAME,
    ISTIO_INGRESS_ROUTE_AUTHENTICATED_NAME,
    ISTIO_INGRESS_ROUTE_UNAUTHENTICATED_NAME,
    DisabledCertHandler,
    GatewayListener,
    GRPCRoute,
    HTTPRoute,
    RefreshCerts,
    RouteInfo,
    clear_conflicting_routes,
    deduplicate_grpc_routes,
    deduplicate_http_routes,
    deduplicate_listeners,
    get_relation_by_name_and_app,
    get_unauthenticated_paths,
    get_unauthenticated_paths_from_istio_ingress_route_configs,
    normalize_ipa_listeners,
    normalize_ipa_routes,
    normalize_istio_ingress_route_grpc_routes,
    normalize_istio_ingress_route_http_routes,
    normalize_istio_ingress_route_listeners,
)

logger = logging.getLogger(__name__)


RESOURCE_TYPES = {
    "Gateway": create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
    ),
    "HTTPRoute": create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "HTTPRoute", "httproutes"
    ),
    "GRPCRoute": create_namespaced_resource(
        "gateway.networking.k8s.io", "v1", "GRPCRoute", "grpcroutes"
    ),
    "ReferenceGrant": create_namespaced_resource(
        "gateway.networking.k8s.io", "v1beta1", "ReferenceGrant", "referencegrants"
    ),
    "DestinationRule": create_namespaced_resource(
        "networking.istio.io", "v1", "DestinationRule", "destinationrules"
    ),
    "RequestAuthentication": create_namespaced_resource(
        "security.istio.io", "v1", "RequestAuthentication", "requestauthentications"
    ),
}

GATEWAY_RESOURCE_TYPES = {RESOURCE_TYPES["Gateway"], Secret, HorizontalPodAutoscaler}
INGRESS_RESOURCE_TYPES = {
    RESOURCE_TYPES["GRPCRoute"],
    RESOURCE_TYPES["ReferenceGrant"],
    RESOURCE_TYPES["HTTPRoute"],
}

GRPC_DESTINATION_RULE_RESOURCE_TYPES = {RESOURCE_TYPES["DestinationRule"]}
REQUEST_AUTH_RESOURCE_TYPES = {RESOURCE_TYPES["RequestAuthentication"]}

GATEWAY_SCOPE = "istio-gateway"
INGRESS_SCOPE = "istio-ingress"
INGRESS_AUTH_POLICY_SCOPE = "istio-ingress-authorization-policy"
EXTZ_AUTH_POLICY_SCOPE = "external-authorizer-authorization-policy"
EXTERNAL_TRAFFIC_AUTH_POLICY_SCOPE = "external-traffic-authorization-policy"
GRPC_DESTINATION_RULE_SCOPE = "grpc-destination-rule"
REQUEST_AUTH_SCOPE = "request-authentication"
DENY_AUTH_POLICY_SCOPE = "deny-without-jwt-authorization-policy"

INGRESS_CONFIG_RELATION = "istio-ingress-config"
FORWARD_AUTH_RELATION = "forward-auth"
REQUEST_AUTH_RELATION = "istio-request-auth"
UPSTREAM_INGRESS_RELATION = "upstream-ingress"
PEERS_RELATION = "peers"


@trace_charm(
    tracing_endpoint="_charm_tracing_endpoint",
    extra_types=[
        MetricsEndpointProvider,
    ],
    # we don't add a cert because istio does TLS his way
    # TODO: fix when https://github.com/canonical/istio-beacon-k8s-operator/issues/33 is closed
)
class IstioIngressCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        # display a status based on the current state
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)

        # Add a custom event that we can emit to request a cert refresh
        self.on.define_event("refresh_certs", RefreshCerts)

        self._ingress_url_ = None

        self.managed_name = f"{self.app.name}-istio"
        self._lightkube_field_manager: str = self.app.name
        self._lightkube_client = None

        # Map of ingress_relation_name to the handler that manages that relation
        self.ingress_relation_handlers = {
            INGRESS_AUTHENTICATED_NAME: IPAv2(
                charm=self,
                relation_name=INGRESS_AUTHENTICATED_NAME,
            ),
            INGRESS_UNAUTHENTICATED_NAME: IPAv2(
                charm=self,
                relation_name=INGRESS_UNAUTHENTICATED_NAME,
            ),
        }

        # Map of istio-ingress-route relation names to handlers
        self.istio_ingress_route_handlers = {
            ISTIO_INGRESS_ROUTE_AUTHENTICATED_NAME: IstioIngressRouteProvider(
                charm=self,
                relation_name=ISTIO_INGRESS_ROUTE_AUTHENTICATED_NAME,
                external_host="",
                tls_enabled=False,
            ),
            ISTIO_INGRESS_ROUTE_UNAUTHENTICATED_NAME: IstioIngressRouteProvider(
                charm=self,
                relation_name=ISTIO_INGRESS_ROUTE_UNAUTHENTICATED_NAME,
                external_host="",
                tls_enabled=False,
            ),
        }
        self.telemetry_labels = generate_telemetry_labels(self.app.name, self.model.name)

        # Setup 'upstream-ingress' relation to allow this istio-ingress to be ingressed
        # through another ingress provider (e.g., to layer multiple ingresses).
        # Accurate data (scheme, port based on TLS) is sent on every reconciliation via
        # provide_ingress_requirements() in _sync_all_resources.
        self.upstream_ingress = IngressPerAppRequirer(
            charm=self,
            relation_name=UPSTREAM_INGRESS_RELATION,
            strip_prefix=True,
            host=self._local_gateway_address,
            port=80,
        )

        # Configure Observability
        self._scraping = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": ["*:15090"]}]}],
        )
        self.charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )
        self._charm_tracing_endpoint = (
            self.charm_tracing.get_endpoint("otlp_http") if self.charm_tracing.relations else None
        )
        self.forward_auth = ForwardAuthRequirer(self)
        self.ingress_config = IngressConfigProvider(
            relation_mapping=self.model.relations, app=self.app
        )
        self.gateway_metadata_provider = GatewayMetadataProvider(
            self,
            relation_name="gateway-metadata",
        )
        self.request_auth_provider = IstioRequestAuthProvider(
            self,
            relation_name=REQUEST_AUTH_RELATION,
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.forward_auth.on.auth_config_changed, self._handle_auth_config)
        self.framework.observe(self.forward_auth.on.auth_config_removed, self._handle_auth_config)
        self.framework.observe(self.on.remove, self._on_remove)
        for relation_handler in self.ingress_relation_handlers.values():
            self.framework.observe(
                relation_handler.on.data_provided, self._on_ingress_data_provided
            )
            self.framework.observe(relation_handler.on.data_removed, self._on_ingress_data_removed)
        for relation_handler in self.istio_ingress_route_handlers.values():
            self.framework.observe(
                relation_handler.on.ready, self._on_istio_ingress_route_ready
            )
            self.framework.observe(
                relation_handler.on.data_removed, self._on_istio_ingress_route_data_removed
            )
        self.framework.observe(
            self.on.metrics_proxy_pebble_ready, self._metrics_proxy_pebble_ready
        )
        self.framework.observe(
            self.on[INGRESS_CONFIG_RELATION].relation_changed, self._handle_ingress_config
        )
        self.framework.observe(
            self.on[INGRESS_CONFIG_RELATION].relation_broken, self._handle_ingress_config
        )
        self.framework.observe(self.on.leader_elected, self._handle_ingress_config)
        self.framework.observe(self.on[PEERS_RELATION].relation_changed, self._on_peers_changed)
        self.framework.observe(self.on[PEERS_RELATION].relation_departed, self._on_peers_changed)
        self.framework.observe(
            self.on["gateway-metadata"].relation_changed, self._on_gateway_metadata_relation_changed
        )
        self.framework.observe(
            self.on[REQUEST_AUTH_RELATION].relation_changed, self._on_request_auth_changed
        )
        self.framework.observe(
            self.on[REQUEST_AUTH_RELATION].relation_broken, self._on_request_auth_changed
        )
        self.framework.observe(
            self.upstream_ingress.on.ready, self._handle_upstream_ingress_changed
        )
        self.framework.observe(
            self.upstream_ingress.on.revoked, self._handle_upstream_ingress_changed
        )

        # During the initialisation of the charm, we do not have a LoadBalancer and thus a LoadBalancer external IP.
        # If we need that IP to request the certs, disable cert handling until we have it.
        # Always use the local gateway address for certs (not cascaded upstream address).
        if (external_hostname := self._local_gateway_address) is None:
            logger.debug(
                "External hostname is not set and no load balancer ip available.  TLS certificate generation disabled"
            )
            self._cert_handler = DisabledCertHandler()
        else:
            self._cert_handler = CertHandler(
                self,
                key="istio-ingress-cert",  # TODO: how is this key used?  if we have two ingresses, do we get issues?
                peer_relation_name=PEERS_RELATION,
                certificates_relation_name="certificates",
                sans=[external_hostname],
                cert_subject=external_hostname,
                # Use a custom event for the charm to signal to the library that we may have changed something
                # meaningful for the CSR.  CertHandler will only regenerate the CSR and obtain new certs if it detects
                # a change when handling this event.
                refresh_events=[self.on.refresh_certs],
            )
            self.framework.observe(
                self._cert_handler.on.cert_changed, self._on_cert_handler_cert_changed
            )

    @property
    def lightkube_client(self):
        """Returns a lightkube client configured for this charm."""
        if self._lightkube_client is None:
            self._lightkube_client = Client(
                namespace=self.model.name, field_manager=self._lightkube_field_manager
            )
        return self._lightkube_client

    def _setup_proxy_pebble_service(self):
        """Define and start the metrics broadcast proxy Pebble service."""
        proxy_container = self.unit.get_container("metrics-proxy")
        if not proxy_container.can_connect():
            return
        proxy_layer = Layer(
            {
                "summary": "Metrics Broadcast Proxy Layer",
                "description": "Pebble layer for the metrics broadcast proxy",
                "services": {
                    "metrics-proxy": {
                        "override": "replace",
                        "summary": "Metrics Broadcast Proxy",
                        "command": "metrics-proxy",
                        "startup": "enabled",
                        "environment": {"POD_LABEL_SELECTOR": self.format_labels(self.telemetry_labels)},
                    }
                },
            }
        )

        proxy_container.add_layer("metrics-proxy", proxy_layer, combine=True)

        try:
            proxy_container.replan()
        except ChangeError as e:
            logger.error(f"Error while replanning proxy container: {e}")

    def _get_gateway_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=GATEWAY_SCOPE
            ),
            resource_types=GATEWAY_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _get_ingress_route_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=INGRESS_SCOPE
            ),
            resource_types=INGRESS_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _get_ingress_auth_policy_resource_manager(self):
        return PolicyResourceManager(
            charm=self,
            lightkube_client=self.lightkube_client,
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=INGRESS_AUTH_POLICY_SCOPE
            ),
            logger=logger,
        )

    def _get_extz_auth_policy_resource_manager(self):
        return PolicyResourceManager(
            charm=self,
            lightkube_client=self.lightkube_client,
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=EXTZ_AUTH_POLICY_SCOPE
            ),
            logger=logger,
        )

    def _get_external_traffic_auth_policy_resource_manager(self):
        return PolicyResourceManager(
            charm=self,
            lightkube_client=self.lightkube_client,
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=EXTERNAL_TRAFFIC_AUTH_POLICY_SCOPE
            ),
            logger=logger,
        )

    def _get_grpc_destination_rule_resource_manager(self):
        """Get KubernetesResourceManager for gRPC DestinationRules."""
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=GRPC_DESTINATION_RULE_SCOPE
            ),
            resource_types=GRPC_DESTINATION_RULE_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _get_request_auth_resource_manager(self):
        """Get KubernetesResourceManager for RequestAuthentication resources."""
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=REQUEST_AUTH_SCOPE
            ),
            resource_types=REQUEST_AUTH_RESOURCE_TYPES,  # pyright: ignore
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _get_deny_auth_policy_resource_manager(self):
        """Get PolicyResourceManager for the DENY-without-JWT authorization policy."""
        return PolicyResourceManager(
            charm=self,
            lightkube_client=self.lightkube_client,
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=DENY_AUTH_POLICY_SCOPE
            ),
            logger=logger,
        )

    def _on_cert_handler_cert_changed(self, _):
        """Event handler for when tls certificates have changed."""
        self._sync_all_resources()

    def _on_config_changed(self, _):
        """Event handler for config changed."""
        self._sync_all_resources()

    def _on_start(self, _):
        """Event handler for start."""
        self._sync_all_resources()

    def _metrics_proxy_pebble_ready(self, _):
        """Event handler for metrics_proxy_pebble_ready."""
        self._sync_all_resources()

    def _handle_ingress_config(self, _):
        """Event handler for ingress_config relation events."""
        self._sync_all_resources()

    def _handle_auth_config(self, _):
        """Event handler for forward_auth config changes."""
        self._sync_all_resources()

    def _on_peers_changed(self, _):
        """Event handler for whenever peer topology changes."""
        self._sync_all_resources()

    def _on_gateway_metadata_relation_changed(self, _):
        """Event handler for gateway-metadata relation events."""
        self._sync_all_resources()

    def _on_request_auth_changed(self, _):
        """Event handler for request-auth relation events."""
        self._sync_all_resources()

    def _on_remove(self, _):
        """Event handler for remove.

        The objective of this handler is to remove all application-scoped resources when the application is being scaled
        to 0 or removed.  We intentionally do not put this removal action behind a leader guard (eg, behind
        `if self.unit.is_leader()`) for the reasons discussed
        [here](https://github.com/canonical/istio-ingress-k8s-operator/issues/16).
        """
        # if there are still units left, skip removal
        if self.model.app.planned_units() > 0:
            logger.info(
                "Handling remove event: skipping resource removal because application is not scaling to 0."
            )
            return
        logger.info(
            "Handling remove event: Attempting to remove application resources because application is scaling to 0."
        )

        # Removing tailing ingress resources
        krm_ingress_routes = self._get_ingress_route_resource_manager()
        krm_ingress_routes.delete()

        self._remove_gateway_resources()

        prm_ingress_authz = self._get_ingress_auth_policy_resource_manager()
        prm_ingress_authz.delete()

        prm_external_authn = self._get_extz_auth_policy_resource_manager()
        prm_external_authn.delete()

        prm_external_traffic_authz = self._get_external_traffic_auth_policy_resource_manager()
        prm_external_traffic_authz.delete()

        krm_request_auth = self._get_request_auth_resource_manager()
        krm_request_auth.delete()

        prm_deny_auth = self._get_deny_auth_policy_resource_manager()
        prm_deny_auth.delete()

    def _on_ingress_data_provided(self, _):
        """Handle a unit providing data requesting IPU."""
        self._sync_all_resources()

    def _on_ingress_data_removed(self, _):
        """Handle a unit removing the data needed to provide ingress."""
        self._sync_all_resources()

    def _on_istio_ingress_route_ready(self, _):
        """Handle a unit providing istio-ingress-route config data."""
        self._sync_all_resources()

    def _on_istio_ingress_route_data_removed(self, _):
        """Handle a unit removing istio-ingress-route relation."""
        self._sync_all_resources()

    def _remove_gateway_resources(self):
        kgm = self._get_gateway_resource_manager()
        kgm.delete()

    def _is_deployment_ready(self) -> bool:
        """Check if the deployment is ready after multiple attempts."""
        timeout = int(self.config["ready-timeout"])
        check_interval = 10
        attempts = timeout // check_interval

        for _ in range(attempts):
            if self._check_deployment_ready():
                return True
            logger.warning("Deployment not ready, retrying...")
            time.sleep(check_interval)

        return False

    def _check_deployment_ready(self) -> bool:
        """Single non-blocking check if the gateway deployment is ready."""
        try:
            deployment = self.lightkube_client.get(
                Deployment, name=self.managed_name, namespace=self.model.name
            )
            return bool(
                deployment.status
                and deployment.status.readyReplicas == deployment.status.replicas
            )
        except ApiError:
            return False

    def _is_load_balancer_ready(self) -> bool:
        """Wait for the LoadBalancer to be created."""
        timeout = int(self.config["ready-timeout"])
        check_interval = 10
        attempts = timeout // check_interval

        for _ in range(attempts):
            lb_status = self._get_lb_external_address
            if lb_status:
                return True

            logger.warning("Loadbalancer not ready, retrying...")
            time.sleep(check_interval)
        return False

    @property
    def _get_lb_external_address(self) -> Optional[str]:
        try:
            lb = self.lightkube_client.get(
                Service, name=self.managed_name, namespace=self.model.name
            )
        except ApiError:
            return None

        if not (status := getattr(lb, "status", None)):
            return None
        if not (load_balancer_status := getattr(status, "loadBalancer", None)):
            return None
        if not (ingress_addresses := getattr(load_balancer_status, "ingress", None)):
            return None
        if not (ingress_address := ingress_addresses[0]):
            return None

        return ingress_address.hostname or ingress_address.ip

    def _is_ready(self) -> bool:
        return self._is_deployment_ready() and self._is_load_balancer_ready()

    def _construct_gateway_tls_secret(self):
        """Return the TLS secret resource for the gateway if TLS is configured, otherwise None."""
        if not self._cert_handler.available:
            return None

        return Secret(
            metadata=ObjectMeta(name=self._certificate_secret_name),
            stringData={
                "tls.crt": self._cert_handler.server_cert,
                "tls.key": self._cert_handler.private_key,
            },
        )

    def _construct_gateway(self, normalized_listeners: List[GatewayListener]):
        """Construct the Gateway resource from normalized listeners.

        This method constructs a Gateway from a list of normalized listeners that have already
        been merged and deduplicated. Each normalized listener contains:
        - port: The port number
        - gateway_protocol: "HTTP" or "HTTPS"
        - tls_secret_name: Optional TLS secret for HTTPS listeners
        - source_app: Source application (for debugging/logging)

        Args:
            normalized_listeners: List of normalized Gateway listeners

        Returns:
            Gateway lightkube resource
        """
        allowed_routes = AllowedRoutes(namespaces={"from": "All"})
        # Use local gateway address for the K8s Gateway resource hostname,
        # not the cascaded upstream address
        hostname = self._local_gateway_address if self._is_valid_hostname(self._local_gateway_address) else None

        listeners = []
        for norm_listener in normalized_listeners:
            # Derive listener name from Gateway protocol and port
            listener_name = f"{norm_listener['gateway_protocol'].lower()}-{norm_listener['port']}"

            listener = Listener(
                name=listener_name,
                port=norm_listener["port"],
                protocol=norm_listener["gateway_protocol"],
                allowedRoutes=allowed_routes,
                hostname=hostname,
            )

            # Add TLS config if this is an HTTPS listener
            if norm_listener["gateway_protocol"] == "HTTPS" and norm_listener["tls_secret_name"]:
                listener.tls = GatewayTLSConfig(
                    certificateRefs=[SecretObjectReference(name=norm_listener["tls_secret_name"])]
                )

            listeners.append(listener)

        gateway = IstioGatewayResource(
            metadata=Metadata(
                name=self.app.name,
                namespace=self.model.name,
                labels={**self.telemetry_labels},
            ),
            spec=IstioGatewaySpec(
                gatewayClassName="istio",
                listeners=listeners,
            ),
        )
        gateway_resource = RESOURCE_TYPES["Gateway"]
        return gateway_resource(
            metadata=ObjectMeta.from_dict(gateway.metadata.model_dump()),
            spec=gateway.spec.model_dump(exclude_none=True),
        )

    def _construct_auth_policy_from_ingress_to_target(
        self, target_name: str, target_namespace: str, target_ports: List[int]
    ):
        """Return an AuthorizationPolicy that allows the ingress workload to communicate with the target workload."""
        return AuthorizationPolicy(
            metadata=ObjectMeta(
                name=target_name + "-" + self.app.name + "-" + target_namespace + "-l4",
                namespace=target_namespace,
            ),
            spec=AuthorizationPolicySpec(
                rules=[
                    Rule(
                        to=[To(operation=Operation(ports=[str(p) for p in sorted(target_ports)]))],
                        from_=[  # type: ignore # this is accessible via an alias "from"
                            # The ServiceAccount that is used to deploy the Gateway (ingress) workload
                            From(
                                source=Source(
                                    principals=[
                                        get_peer_identity_for_juju_application(
                                            self.managed_name, self.model.name
                                        )
                                    ]
                                )
                            )
                        ],
                    )
                ],
                selector=WorkloadSelector(matchLabels={"app.kubernetes.io/name": target_name}),
                action=Action.allow,
            ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
        )

    def _construct_ext_authz_policy(
        self, ext_authz_provider_name: str, unauthenticated_paths: List[str]
    ):
        """Return an AuthorizationPolicy that applies authentication to all paths except unauthenticated_paths."""
        # When request-auth is active, skip ext-authz for requests with a Bearer token
        when_conditions = None
        if self.request_auth_provider.is_ready:
            when_conditions = [
                Condition(key="request.headers[authorization]", notValues=["Bearer *"])
            ]

        if unauthenticated_paths:
            auth_rule = Rule(
                to=[To(operation=Operation(notPaths=unauthenticated_paths))],
                when=when_conditions,
            )
        else:
            auth_rule = Rule(when=when_conditions)

        return AuthorizationPolicy(
            metadata=ObjectMeta(
                name=f"ext-authz-{self.app.name}",
                namespace=self.model.name,
            ),
            spec=AuthorizationPolicySpec(
                rules=[auth_rule],
                targetRefs=[
                    PolicyTargetReference(
                        kind="Gateway",
                        group="gateway.networking.k8s.io",
                        name=self.app.name,
                    )
                ],
                action=Action.custom,
                provider=Provider(name=ext_authz_provider_name),
            ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
        )

    def _construct_external_traffic_auth_policy(self, ip_blocks: List[str]):
        """Return an AuthorizationPolicy that allows external traffic from specified IP blocks.

        Args:
            ip_blocks: List of CIDR blocks to allow traffic from (e.g., ["0.0.0.0/0"])
        """
        return AuthorizationPolicy(
            metadata=ObjectMeta(
                name=f"{self.app.name}-{self.model.name}-external-traffic",
                namespace=self.model.name,
            ),
            spec=AuthorizationPolicySpec(
                rules=[
                    Rule(
                        from_=[From(source=Source(ipBlocks=ip_blocks))],  # type: ignore
                    )
                ],
                targetRefs=[
                    PolicyTargetReference(
                        kind="Gateway",
                        group="gateway.networking.k8s.io",
                        name=self.app.name,
                    )
                ],
                action=Action.allow,
            ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
        )

    def _construct_hpa(self, unit_count: int) -> HorizontalPodAutoscaler:
        return HorizontalPodAutoscaler(
            metadata=ObjectMeta(name=self.app.name, namespace=self.model.name),
            spec=HorizontalPodAutoscalerSpec(
                scaleTargetRef=CrossVersionObjectReference(
                    apiVersion="apps/v1",
                    kind="Deployment",
                    name=self.managed_name,
                ),
                minReplicas=unit_count,
                maxReplicas=unit_count,
            ),
        )

    def _is_tls_enabled(self) -> bool:
        return self._construct_gateway_tls_secret() is not None

    def _get_normalized_istio_routes(self) -> Tuple[List[HTTPRoute],List[GRPCRoute]]:
        """Return the normalized Istio routes."""
        is_tls_enabled = self._is_tls_enabled()
        istio_ingress_route_configs = self._get_istio_ingress_route_configs()
        istio_http_routes = normalize_istio_ingress_route_http_routes(
            istio_ingress_route_configs, is_tls_enabled, self.app.name
        )
        istio_grpc_routes = normalize_istio_ingress_route_grpc_routes(
            istio_ingress_route_configs, is_tls_enabled, self.app.name
        )
        return istio_http_routes, istio_grpc_routes

    def _get_normalized_ipa_routes(self) -> List[HTTPRoute]:
        """Return the normalized IPA routes from both sources."""
        return normalize_ipa_routes(self._get_routes(), self._is_tls_enabled(), self.app.name)

    def _convert_to_jwt_rules(self, interface_jwt_rules: list) -> List[JWTRule]:
        """Convert interface JWTRule models to Istio CRD JWTRule models."""
        istio_jwt_rules = []
        for rule in interface_jwt_rules:
            claim_to_headers = None
            if rule.claim_to_headers:
                claim_to_headers = [
                    ClaimToHeader(header=c.header, claim=c.claim) for c in rule.claim_to_headers
                ]

            from_headers = None
            if rule.from_headers:
                from_headers = [
                    FromHeader(name=h.name, prefix=h.prefix) for h in rule.from_headers
                ]

            istio_jwt_rules.append(
                JWTRule(
                    issuer=rule.issuer,
                    jwksUri=rule.jwks_uri,
                    audiences=rule.audiences,
                    forwardOriginalToken=rule.forward_original_token,
                    outputClaimToHeaders=claim_to_headers,
                    fromHeaders=from_headers,
                )
            )
        return istio_jwt_rules

    def _construct_request_authentication(self, app_name: str, jwt_rules: List[JWTRule]):
        """Construct a RequestAuthentication resource for a related app."""
        return RESOURCE_TYPES["RequestAuthentication"](
            metadata=ObjectMeta(
                name=f"request-auth-{app_name}-{self.app.name}",
                namespace=self.model.name,
            ),
            spec=RequestAuthenticationSpec(
                targetRefs=[
                    PolicyTargetReference(
                        kind="Gateway",
                        group="gateway.networking.k8s.io",
                        name=self.app.name,
                    )
                ],
                jwtRules=jwt_rules,
            ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
        )

    def _construct_deny_without_jwt_policy(self, bearer_only: bool = False):
        """Construct a DENY policy that rejects requests without a validated JWT principal.

        Args:
            bearer_only: When True, the DENY policy only applies to requests carrying a Bearer
                token.  This is used when forward-auth is active so that non-Bearer requests
                continue to flow through ext-authz while Bearer requests that bypass ext-authz
                are still caught by the DENY rule.
        """
        when_conditions = None
        if bearer_only:
            when_conditions = [
                Condition(
                    key="request.headers[authorization]", values=["Bearer *"]
                )
            ]

        return AuthorizationPolicy(
            metadata=ObjectMeta(
                name=f"deny-without-jwt-{self.app.name}",
                namespace=self.model.name,
            ),
            spec=AuthorizationPolicySpec(
                action=Action.deny,
                rules=[
                    Rule(
                        from_=[From(source=Source(notRequestPrincipals=["*"]))],  # type: ignore[call-arg]
                        when=when_conditions,
                    )
                ],
                targetRefs=[
                    PolicyTargetReference(
                        kind="Gateway",
                        group="gateway.networking.k8s.io",
                        name=self.app.name,
                    )
                ],
            ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
        )

    def _sync_request_authentication(self):
        """Reconcile RequestAuthentication resources from request-auth relations.

        Creates RequestAuthentication resources only for apps with valid JWT rules.
        Apps with malformed or missing data are logged and skipped — security is enforced
        by the DENY policy which blocks requests without a validated JWT principal.
        """
        krm = self._get_request_auth_resource_manager()

        connected_apps = self.request_auth_provider.get_connected_apps()
        valid_data = self.request_auth_provider.get_data()
        malformed_apps = connected_apps - set(valid_data.keys())

        for app_name in sorted(malformed_apps):
            logger.error(
                "Application %s is connected over istio-request-auth "
                "but has not provided valid jwt_rules",
                app_name,
            )

        resources = []
        for app_name, interface_jwt_rules in valid_data.items():
            jwt_rules = self._convert_to_jwt_rules(interface_jwt_rules)
            resources.append(self._construct_request_authentication(app_name, jwt_rules))

        krm.reconcile(resources)

    def _sync_deny_auth_policy(self):
        """Reconcile the DENY-without-JWT authorization policy.

        The DENY policy is created whenever any application is connected over the
        istio-request-auth relation, regardless of whether the data is valid.  This
        ensures fail-closed behaviour: malformed apps cannot leave the gateway open.

        When forward-auth (ext-authz) is also active the DENY policy is scoped to
        Bearer-token requests only so that non-Bearer requests continue to be handled
        by ext-authz.
        """
        policy_manager = self._get_deny_auth_policy_resource_manager()
        resources = []

        has_request_auth = bool(self.request_auth_provider.get_connected_apps())
        has_forward_auth = bool(self._get_oauth_decisions_address())

        if has_request_auth:
            resources.append(
                self._construct_deny_without_jwt_policy(bearer_only=has_forward_auth)
            )

        policy_manager.reconcile(policies=[], mesh_type=MeshType.istio, raw_policies=resources)

    def _sync_all_resources(self):
        """Synchronize all resources including authentication, gateway, ingress, and certificates.

        Flow:
        * Check authentication configuration.
        * Publish or clear the auth_decisions_address in ingress-config, if related.
        * If auth relation exists but no decisions address, set to blocked and remove gateway.
        * Fetch route information from the ingress relation.
        * Fetch route and listeners information from the istio-ingress-route relation.
        * Aggregate and deduplicate the routes and listeners from all supported ingress relations.
        * Synchronize external authorization configuration.
            - If missing valid ingress-config relation when auth is provided, remove gateway.
        * Reconcile HPA and gateway resources to align replicas with unit count and ensure gateway readiness.
        * Validate the external hostname.
        * Synchronize ingress resources.
        * Publish route information to ingressed applications
        * Set up the proxy service.
        * Update forward auth relation data with ingressed apps.
        * Request certificate inspection.
        """
        if not self.unit.is_leader():
            return

        # Check authentication configuration.
        auth_decisions_address = self._get_oauth_decisions_address()
        forward_auth_headers = self._get_forward_auth_headers()

        # Publish or clear the auth_decisions_address in ingress-config, if related.
        if self.model.get_relation(INGRESS_CONFIG_RELATION):
            self._publish_to_istio_ingress_config_relation(auth_decisions_address, forward_auth_headers)

        # If auth relation exists but no decisions address, remove gateway.
        if self.model.get_relation(FORWARD_AUTH_RELATION) and not auth_decisions_address:
            self._remove_gateway_resources()
            return

        # Fetch raw route data from both IPA and istio-ingress-route
        application_route_data = self._get_routes()
        istio_ingress_route_configs = self._get_istio_ingress_route_configs()

        # Normalize data to common intermediate formats
        tls_secret_name = self._certificate_secret_name if self._is_tls_enabled() else None

        # Normalize listeners from both sources
        ipa_listeners = normalize_ipa_listeners(tls_secret_name)
        istio_listeners = normalize_istio_ingress_route_listeners(
            istio_ingress_route_configs, tls_secret_name
        )

        # Normalize routes from both sources
        ipa_http_routes = self._get_normalized_ipa_routes()
        istio_http_routes, istio_grpc_routes = self._get_normalized_istio_routes()

        # Merge and deduplicate using source-agnostic functions
        unique_listeners = deduplicate_listeners(ipa_listeners + istio_listeners)
        valid_http_routes, http_apps_to_clear = deduplicate_http_routes(ipa_http_routes + istio_http_routes)
        valid_grpc_routes, grpc_apps_to_clear = deduplicate_grpc_routes(istio_grpc_routes)  # ipa relation doesnt support grpc routes.

        # Clear conflicts from original structures (needed for publishing back to apps)
        all_apps_to_clear = http_apps_to_clear | grpc_apps_to_clear
        clear_conflicting_routes(
            application_route_data, istio_ingress_route_configs, all_apps_to_clear
        )

        # Extract unauthenticated paths (still uses original cleared structures)
        unauthenticated_paths = get_unauthenticated_paths(application_route_data)
        unauthenticated_paths.extend(
            get_unauthenticated_paths_from_istio_ingress_route_configs(
                istio_ingress_route_configs
            )
        )

        # Synchronize external authorization configuration.
        if not self.ingress_config.is_ready() and auth_decisions_address:
            self._remove_gateway_resources()
            return
        self._sync_ext_authz_auth_policy(auth_decisions_address, unauthenticated_paths)
        self._sync_external_traffic_auth_policy()
        self._sync_request_authentication()
        self._sync_deny_auth_policy()

        # Reconcile HPA and gateway resources

        self._sync_gateway_resources(unique_listeners)
        if not self._is_ready():
            return

        # Validate external hostname.
        if not self._ingress_url:
            return

        # Update upstream ingress relation with current host, port, and scheme.
        # This ensures the upstream always has fresh data about how to reach this gateway.
        # No-op if no upstream ingress is related.
        self.upstream_ingress.provide_ingress_requirements(
            **self._generate_upstream_ingress_route_configuration()
        )

        # Synchronize ingress resources
        try:
            self._sync_ingress_resources(
                http_routes=valid_http_routes, grpc_routes=valid_grpc_routes
            )
        except ApiError as e:
            logger.error("Ingress sync failed: %s", e)
            raise e

        # Publish route information to ingressed applications (IPA)
        self._publish_routes_to_ingressed_applications(application_route_data)

        # Publish istio-ingress-route data (external_host + tls_enabled) to apps without conflicts
        self._publish_istio_ingress_route_data(istio_ingress_route_configs, all_apps_to_clear)

        # Set up the proxy service.
        self._setup_proxy_pebble_service()

        # Update forward auth relation data with ingressed apps.
        if self.model.get_relation(FORWARD_AUTH_RELATION):
            ingressed_apps = [app for app, _ in application_route_data.keys()]
            self.forward_auth.update_requirer_relation_data(
                ForwardAuthRequirerConfig(ingress_app_names=ingressed_apps)
            )

        # Publish gateway metadata to related charms
        self._publish_gateway_metadata()

        # Request certificate inspection.
        # Request a cert refresh in case configuration has changed
        # The cert handler will only refresh if it detects a meaningful change
        logger.info(
            "Requesting CertHandler inspect certs to decide if our CSR has changed and we should re-request"
        )
        self.on.refresh_certs.emit()

    def _on_collect_status(self, event: CollectStatusEvent):
        """Collect unit status from sub-collectors."""
        if not self.unit.is_leader():
            self._collect_leadership_status(event)
            return

        self._collect_auth_decisions_status(event)
        self._collect_route_collision_status(event)
        self._collect_external_authorization_status(event)
        self._collect_readiness_status(event)
        self._collect_external_hostname_status(event)
        event.add_status(ActiveStatus(f"Serving at {self._ingress_url}"))

    def _collect_leadership_status(self, event: CollectStatusEvent):
        """Non-leader units are considered active."""
        event.add_status(ActiveStatus("Backup unit; standing by for leader takeover"))

    def _collect_auth_decisions_status(self, event: CollectStatusEvent):
        """Set to blocked if auth relation exists but no decisions address.

        (Should be called on the leader unit only.)
        """
        auth_decisions_address = self._get_oauth_decisions_address()
        if self.model.get_relation(FORWARD_AUTH_RELATION) and not auth_decisions_address:
            event.add_status(BlockedStatus("Authentication configuration incomplete; ingress is disabled."))

    def _collect_route_collision_status(self, event: CollectStatusEvent):
        """Set to blocked if routes have been removed.

        (Should be called on the leader unit only.)
        """
        if self._are_routes_removed():
            event.add_status(BlockedStatus("Route conflict detected. Check the logs for more information."))

    def _are_routes_removed(self) -> bool:
        """Return if there are routes removed because of collision."""
        ipa_http_routes = self._get_normalized_ipa_routes()
        istio_http_routes, istio_grpc_routes = self._get_normalized_istio_routes()
        _, http_apps_to_clear = deduplicate_http_routes(ipa_http_routes + istio_http_routes)
        _, grpc_apps_to_clear = deduplicate_grpc_routes(istio_grpc_routes)
        all_apps_to_clear = http_apps_to_clear | grpc_apps_to_clear
        return len(all_apps_to_clear) > 0

    def _collect_external_authorization_status(self, event: CollectStatusEvent):
        """Block if Ingress configuration relation missing, but valid authentication configuration are provided.

        (Should be called on the leader unit only.)
        """
        auth_decisions_address = self._get_oauth_decisions_address()
        if not self.ingress_config.is_ready() and auth_decisions_address:
            event.add_status(BlockedStatus("Ingress configuration relation missing, yet valid authentication configuration are provided."))

    def _collect_readiness_status(self, event: CollectStatusEvent):
        """Set to maintenance/blocked if gateway resources are not ready.

        Uses non-blocking single checks to avoid blocking the charm agent.
        """
        deployment_ready = self._check_deployment_ready()
        lb_ready = bool(self._get_lb_external_address)

        if deployment_ready and lb_ready:
            return

        event.add_status(MaintenanceStatus("Validating gateway readiness"))
        if not deployment_ready:
            event.add_status(BlockedStatus("Gateway k8s deployment not ready, is istio properly installed?"))
        if not lb_ready:
            event.add_status(BlockedStatus("Gateway load balancer is unable to obtain an IP or hostname from the cluster."))

    def _collect_external_hostname_status(self, event: CollectStatusEvent):
        """Block on invalid external hostname.

        (Should be called on the leader unit only.)
        """
        if not self._ingress_url:
            event.add_status(BlockedStatus("Invalid hostname provided, Please ensure this adheres to RFC 1123."))

    def _get_oauth_decisions_address(self) -> Optional[str]:
        """Retrieve the auth configuration decisions_address if it exists.

        Returns:
            The decisions_address if available; otherwise, None.
        """
        auth_info = self.forward_auth.get_provider_info()
        if not auth_info:
            logger.debug("Auth relation exists but auth_info is missing.")
            return None

        if not auth_info.decisions_address:
            logger.debug("Auth relation exists but decisions_address is missing.")
            return None

        return auth_info.decisions_address

    def _get_forward_auth_headers(self) -> Optional[List[str]]:
        """Retrieve auth headers from forward-auth relation if available.

        Returns:
            List of headers if provided by the auth provider; otherwise, None.
        """
        auth_info = self.forward_auth.get_provider_info()
        if not auth_info:
            logger.debug("Auth relation exists but auth_info is missing.")
            return None
        if not auth_info.headers:
            logger.warning("Auth relation exists but headers are missing; using default headers.")
            return None
        return auth_info.headers

    def _get_routes(self):
        """Return the routes requested by all applications on all ingress relations, and associated relation_handlers.

        Returns:
            A dict mapping (app_name, relation_name): {"handler": relation_handler, "routes": routes}, where
            relation_handler is a valid serializer and deserializer for this (app_name, relation_name)'s relation data.
        """
        routes = {}
        for relation_name in self.ingress_relation_handlers.keys():
            for app_name, app_route_data in self._get_routes_from_ingress(relation_name).items():
                route_key = (app_name, relation_name)
                routes[route_key] = app_route_data

        return routes

    def _get_istio_ingress_route_configs(self):
        """Return the istio-ingress-route configs from all related applications.

        Returns:
            A dict mapping (app_name, relation_name): {"handler": relation_handler, "config": IstioIngressRouteConfig | None}
        """
        configs = {}
        for relation_name, handler in self.istio_ingress_route_handlers.items():
            for rel in self.model.relations.get(relation_name, []):
                app_name = rel.app.name
                route_key = (app_name, relation_name)
                config = handler.get_config(rel) if rel.active else None
                configs[route_key] = {"handler": handler, "config": config}
        return configs

    def _get_routes_from_ingress(self, relation_name: str):
        """Retrieve all routes from the given relation, and associated relation_handlers.

        Args:
            relation_name: The name of the ingress relation.

        Returns:
            A dict of {app_name: {"handler": relation_handler, "routes": List[RouteInfo])}.  In the case where a related
            app has not provided any data yet, [RouteInfo] will be an empty list.
        """
        # {key: {"handler": relation_handler, "routes": [RouteInfo]}}
        application_route_data = {}

        # Presently, each relation endpoint supports a single relation handler, so we can just look it up.
        # But in future if we support ingress v2 and v3 simultaneously, we'd need to include in the below loop something
        # to inspect each related app and choose a handler.
        relation_handler = self.ingress_relation_handlers[relation_name]

        for rel in self.model.relations[relation_name]:
            key = rel.app.name
            if key not in application_route_data:
                application_route_data[key] = {"handler": relation_handler, "routes": []}

            if not rel.active or not relation_handler.is_ready(rel):
                # No active routes for this related application
                continue

            data = relation_handler.get_data(rel)
            application_route_data[key]["routes"].append(
                RouteInfo(
                    service_name=data.app.name,
                    namespace=data.app.model,
                    port=data.app.port,
                    # For data.app.strip_prefix, an omitted value (None) equates to False
                    strip_prefix=data.app.strip_prefix or False,
                    prefix=self._generate_default_path(data.app.name, data.app.model),
                )
            )
        return application_route_data

    def _publish_routes_to_ingressed_applications(self, route_data):
        """Update the ingress relation for all routes."""
        ingress_url = self._ingress_url_with_scheme()
        for (app_name, relation_name), this_route_data in route_data.items():
            relation_handler = this_route_data["handler"]
            routes = this_route_data["routes"]
            rel = get_relation_by_name_and_app(self.model.relations[relation_name], app_name)

            if len(routes) != 1:
                if len(routes) > 1:
                    # This is unsupported and should never happen, but just in case.
                    logger.error(
                        f"Cannot publish routes to {app_name} in {relation_name} because there are too many routes."
                        f"  Expected <=1 route, got {routes}"
                    )
                relation_handler.wipe_ingress_data(rel)
                continue

            relation_handler.publish_url(rel, ingress_url + routes[0]["prefix"])

    def _publish_istio_ingress_route_data(
        self, istio_ingress_route_configs: Dict, apps_to_clear: set
    ):
        """Update istio-ingress-route relations with external host and TLS status.

        For apps with route conflicts, clears the relation data (using wipe_ingress_data).
        For apps without conflicts, publishes the external_host and tls_enabled status.

        Args:
            istio_ingress_route_configs: Dict mapping (app_name, relation_name) to config data
            apps_to_clear: Set of (app_name, relation_name) tuples that have conflicts
        """
        is_tls_enabled = self._construct_gateway_tls_secret() is not None

        for (app_name, relation_name), config_data in istio_ingress_route_configs.items():
            relation_handler = config_data["handler"]
            app_key = (app_name, relation_name)
            rel = get_relation_by_name_and_app(self.model.relations[relation_name], app_name)

            if app_key in apps_to_clear:
                # Clear relation data for apps with conflicts (similar to IPA wipe_ingress_data)
                relation_handler.wipe_ingress_data(rel)
                logger.debug(
                    f"Cleared istio-ingress-route data for {app_name} on {relation_name} due to route conflict"
                )
            else:
                # Publish ingress address for apps without conflicts
                relation_handler.update_ingress_address(
                    external_host=self._ingress_url,
                    tls_enabled=is_tls_enabled,
                )

    def _publish_to_istio_ingress_config_relation(
        self, decisions_address: Optional[str], forward_auth_headers: Optional[List[str]]
    ):
        if not decisions_address:
            self.ingress_config.clear()
            return

        parsed_url = urlparse(decisions_address)
        service_name = parsed_url.hostname
        port = parsed_url.port
        # TODO: Below probably needs to be leader guarded
        # we should think about this as part of working on #issues/16
        # The forward-auth lib currently only provides upstream-facing headers (headersToUpstreamOnAllow).
        # For other header types, we use standard defaults until the forward-auth interface is extended.
        self.ingress_config.publish(
            ext_authz_service_name=service_name,
            ext_authz_port=str(port),
            include_headers_in_check=DEFAULT_INCLUDE_HEADERS_IN_CHECK,
            headers_to_upstream_on_allow=forward_auth_headers or DEFAULT_HEADERS_TO_UPSTREAM_ON_ALLOW,
            headers_to_downstream_on_allow=DEFAULT_HEADERS_TO_DOWNSTREAM_ON_ALLOW,
            headers_to_downstream_on_deny=DEFAULT_HEADERS_TO_DOWNSTREAM_ON_DENY,
        )

    def _sync_ext_authz_auth_policy(
        self, auth_decisions_address: Optional[str], unauthenticated_paths: List[str]
    ):
        """Reconcile the AuthorizationPolicy that applies authentication to this gateway."""
        policy_manager = self._get_extz_auth_policy_resource_manager()
        resources = []

        if self.ingress_config.is_ready() and auth_decisions_address:
            provider_name = self.ingress_config.get_ext_authz_provider_name()
            resources.append(self._construct_ext_authz_policy(provider_name, unauthenticated_paths=unauthenticated_paths))  # type: ignore

        policy_manager.reconcile(policies=[], mesh_type=MeshType.istio, raw_policies=resources)

    def _sync_external_traffic_auth_policy(self):
        """Reconcile the AuthorizationPolicy that allows external traffic to the gateway."""
        policy_manager = self._get_external_traffic_auth_policy_resource_manager()
        cidrs_config = cast(str, self.config["external-traffic-policy-cidrs"])
        ip_blocks = [cidr.strip() for cidr in cidrs_config.split(",") if cidr.strip()]
        resources = [self._construct_external_traffic_auth_policy(ip_blocks)]
        policy_manager.reconcile(policies=[], mesh_type=MeshType.istio, raw_policies=resources)

    def _sync_gateway_resources(self, normalized_listeners: List[GatewayListener]):
        """Synchronize Gateway resources using normalized listeners.

        Args:
            normalized_listeners: List of normalized Gateway listeners (already merged and deduplicated)
        """
        unit_count = self.model.app.planned_units()
        krm = self._get_gateway_resource_manager()
        resources_list = []

        # Skip reconciliation if no units are left (unit_count < 1):
        #  - This typically indicates an application removal event; we rely on the remove hook for cleanup.
        #  - Attempting to reconcile with an HPA that sets replicas to zero is invalid.
        #  - This guard exists because some events can call _sync_all_resources before the remove hook runs,
        #    leading to k8s validation webhook errors when planned_units is 0.
        if unit_count > 0:
            if secret := self._construct_gateway_tls_secret():
                resources_list.append(secret)

            resources_list.append(self._construct_gateway(normalized_listeners))
            resources_list.append(self._construct_hpa(unit_count))

        # Use PatchType.MERGE for Gateway resources to remove any stale fields in the resource with the same name.
        # This ensures:
        # 1. Stale listeners are removed when protocols change (e.g., http-8080 -> https-8080)
        # 2. Omitted fields like hostname are properly removed from the resource
        # Without MERGE, Server-Side Apply accumulates stale listeners and preserves omitted fields.
        krm.reconcile(resources_list, patch_type=PatchType.MERGE)

    def _construct_httproutes(self, http_routes: List[HTTPRoute]) -> List:
        """Construct HTTPRoute K8s resources from normalized HTTP routes.

        This method is fully source-agnostic - normalized data already contains charm models.

        Args:
            http_routes: List of normalized, deduplicated HTTP routes with charm models

        Returns:
            List of HTTPRoute lightkube resources
        """
        httproutes = []

        for route in http_routes:
            # Derive listener name from Gateway protocol and port
            listener_name = f"{route['listener_protocol'].lower()}-{route['listener_port']}"

            # Construct HTTPRoute resource from normalized data
            http_route_resource = HTTPRouteResource(
                metadata=Metadata(
                    name=route["name"],
                    namespace=route["namespace"],
                ),
                spec=HTTPRouteResourceSpec(
                    parentRefs=[
                        ParentRef(
                            name=self.app.name,
                            namespace=self.model.name,
                            sectionName=listener_name,
                        )
                    ],
                    rules=[
                        HTTPRouteRule(
                            matches=route["matches"],  # Already charm HTTPRouteMatch models
                            backendRefs=route["backend_refs"],  # Already charm BackendRef models
                            filters=route["filters"] if route["filters"] else None,
                        )
                    ],
                ),
            )

            # Convert to lightkube resource
            httproute_lk_resource = RESOURCE_TYPES["HTTPRoute"]
            httproutes.append(
                httproute_lk_resource(
                    metadata=ObjectMeta.from_dict(http_route_resource.metadata.model_dump()),
                    spec=http_route_resource.spec.model_dump(exclude_none=True),
                )
            )

        return httproutes

    def _construct_grpcroutes(self, grpc_routes: List[GRPCRoute]) -> List:
        """Construct GRPCRoute K8s resources from normalized gRPC routes.

        This method is fully source-agnostic - normalized data already contains charm models.

        Args:
            grpc_routes: List of normalized, deduplicated gRPC routes with charm models

        Returns:
            List of GRPCRoute lightkube resources
        """
        grpcroutes = []

        for route in grpc_routes:
            # Derive listener name from Gateway protocol and port
            listener_name = f"{route['listener_protocol'].lower()}-{route['listener_port']}"

            # Construct GRPCRoute resource from normalized data
            grpc_route_resource = GRPCRouteResource(
                metadata=Metadata(
                    name=route["name"],
                    namespace=route["namespace"],
                ),
                spec=GRPCRouteResourceSpec(
                    parentRefs=[
                        ParentRef(
                            name=self.app.name,
                            namespace=self.model.name,
                            sectionName=listener_name,
                        )
                    ],
                    rules=[
                        GRPCRouteRule(
                            matches=route["matches"],  # Already charm GRPCRouteMatch models
                            backendRefs=route["backend_refs"],  # Already charm BackendRef models
                            filters=route["filters"] if route["filters"] else None,
                        )
                    ],
                ),
            )

            # Convert to lightkube resource
            grpcroute_lk_resource = RESOURCE_TYPES["GRPCRoute"]
            grpcroutes.append(
                grpcroute_lk_resource(
                    metadata=ObjectMeta.from_dict(grpc_route_resource.metadata.model_dump()),
                    spec=grpc_route_resource.spec.model_dump(exclude_none=True),
                )
            )

        return grpcroutes

    def _construct_auth_policies(
        self, http_routes: List[HTTPRoute], grpc_routes: List[GRPCRoute]
    ) -> List:
        """Construct L4 authorization policies from normalized routes.

        This method is fully source-agnostic - extracts backend info from normalized routes.
        Creates one auth policy per unique (service, namespace) backend, aggregating all ports.

        Args:
            http_routes: List of normalized HTTP routes
            grpc_routes: List of normalized gRPC routes

        Returns:
            List of AuthorizationPolicy lightkube resources
        """
        # Collect all ports per (service, namespace) backend
        backend_ports: dict = {}

        for route in http_routes:
            for backend_ref in route["backend_refs"]:
                key = (backend_ref.name, backend_ref.namespace)
                backend_ports.setdefault(key, set()).add(backend_ref.port)

        for route in grpc_routes:
            for backend_ref in route["backend_refs"]:
                key = (backend_ref.name, backend_ref.namespace)
                backend_ports.setdefault(key, set()).add(backend_ref.port)

        return [
            self._construct_auth_policy_from_ingress_to_target(
                target_name=name,
                target_namespace=namespace,
                target_ports=list(ports),
            )
            for (name, namespace), ports in backend_ports.items()
        ]

    def _construct_grpc_destination_rules(self, grpc_routes: List[GRPCRoute]) -> List:
        """Construct DestinationRules for gRPC backends.

        Creates one DestinationRule per unique (service, namespace) backend
        with useClientProtocol=true to preserve gRPC protocol through gateway.

        Args:
            grpc_routes: List of normalized gRPC routes

        Returns:
            List of DestinationRule lightkube resources
        """
        destination_rules = []
        seen_backends = set()

        for route in grpc_routes:
            for backend_ref in route["backend_refs"]:
                # One DR per unique (service, namespace) - not per port
                backend_key = (backend_ref.name, backend_ref.namespace)
                if backend_key not in seen_backends:
                    seen_backends.add(backend_key)

                    # Build FQDN host
                    host = f"{backend_ref.name}.{backend_ref.namespace}.svc.cluster.local"

                    # Name: {servicename}-grpc-dest-rule-{ingresscharmname}
                    dr_name = f"{backend_ref.name}-grpc-dest-rule-{self.app.name}"

                    # Create DestinationRule resource in backend's namespace
                    dr_resource = RESOURCE_TYPES["DestinationRule"](
                        metadata=ObjectMeta(
                            name=dr_name,
                            namespace=backend_ref.namespace,  # Backend's namespace (same as routes)
                        ),
                        spec={
                            "host": host,
                            "trafficPolicy": {
                                "connectionPool": {
                                    "http": {
                                        "useClientProtocol": True
                                    }
                                }
                            }
                        }
                    )
                    destination_rules.append(dr_resource)

        return destination_rules

    def _sync_ingress_resources(self, http_routes: List[HTTPRoute], grpc_routes: List[GRPCRoute]):
        """Synchronize all ingress resources (HTTPRoutes, GRPCRoutes, and L4 auth policies) from normalized data.

        This method works on normalized, deduplicated routes from all sources (IPA and istio-ingress-route).
        It constructs K8s resources source-agnostically.

        Args:
            http_routes: List of normalized, deduplicated HTTP routes
            grpc_routes: List of normalized, deduplicated gRPC routes
        """
        if not self.unit.is_leader():
            raise RuntimeError("Ingress can only be provided on the leader unit.")

        # Construct K8s resources from normalized data
        httproutes = self._construct_httproutes(http_routes)
        grpcroutes = self._construct_grpcroutes(grpc_routes)
        auth_policies = self._construct_auth_policies(http_routes, grpc_routes)

        # NOTE: The below DestinationRule resource instructs the gateway to use same protocol (http/2, http/1.1 etc) as the client.
        # According to the istio docs: https://istio.io/latest/docs/ops/configuration/traffic-management/protocol-selection/#http-gateway-protocol-selection
        # The gateway is unable to determine the protocol of the backend unless explicitly defined using the portname or the appProtocol. By default it wll use http/1.1.
        # This is problematic because for gRPC backends, the gateway uses http/1.1 as well by default (because there is no valid port-name nor appProtocol). Hence gRPC routing fails.
        # The charm has no control neither over the port name (auto generated by Juju) nor over the appProtocol (Juju controls the service so we cant reliably patch this).
        # Hence the only workaround is to create a DestinationRule that instructs the gateway to usee the same protocol as the client request.
        # This makes sure, when client makes a gRPC request, gateway will automatically use the right http/2 protocol.
        grpc_drs = self._construct_grpc_destination_rules(grpc_routes)
        grpc_dr_manager = self._get_grpc_destination_rule_resource_manager()
        grpc_dr_manager.reconcile(grpc_drs)

        # Reconcile all resources
        # The ingress route resource manager handles both HTTPRoute and GRPCRoute
        route_krm = self._get_ingress_route_resource_manager()
        all_routes = httproutes + grpcroutes
        route_krm.reconcile(all_routes)

        kam = self._get_ingress_auth_policy_resource_manager()
        kam.reconcile(policies=[], mesh_type=MeshType.istio, raw_policies=auth_policies)

    def _ingress_url_with_scheme(self) -> str:
        """Return the url to the ingress managed by this charm, including scheme.

        See _ingress_url for more details.

        This may return None if no ingress load balancer exists.
        """
        return f"{self._ingressed_scheme}://{self._ingress_url}"

    @property
    def _ingress_url(self) -> Optional[str]:
        """Return the external address for the ingress gateway.

        This will return one of (in order of preference):
        1. the value cached from a previous call to _ingress_url, even if this value has since changed
        2. the upstream ingress URL if an upstream ingress is configured and ready
        3. the `external-hostname` config if that is set
        4. the load balancer address for the ingress gateway, if it exists and has an IP
        5. None

        Preference is given to the previously cached value because this charm may make several calls to this method in
        a single charm execution and the value of the load balancer address may change during that time.  Without this
        preference, we could request certs for one hostname and then serve traffic on another.

        Only use this directly when _ingress_url is allowed to be None.
        """
        if self._ingress_url_ is not None:
            return self._ingress_url_

        # Cascade: use upstream ingress URL if available
        if self.upstream_ingress.is_ready():
            url = cast(str, self.upstream_ingress.url)
            parsed = urlparse(url)
            address = url.replace(f"{parsed.scheme}://", "", 1).rstrip("/")
            self._ingress_url_ = address
            return self._ingress_url_

        # Fallback to local gateway address
        if local_address := self._local_gateway_address:
            self._ingress_url_ = local_address
            return self._ingress_url_

        logger.debug(
            "Load balancer address not available.  This is likely a transient issue that will resolve itself, but"
            " could be because the cluster does not have a load balancer provider.  Defaulting to this charm's fqdn."
        )

        return None

    @property
    def _local_gateway_address(self) -> Optional[str]:
        """Return the LOCAL address of this gateway (external_hostname or LB address).

        Unlike _ingress_url (which cascades through upstream ingress), this always
        returns the direct address of this gateway. Used to tell the upstream ingress
        where to route traffic to reach this gateway, and for CertHandler SANs.
        """
        if external_hostname := self.model.config.get("external_hostname"):
            hostname = cast(str, external_hostname)
            if self._is_valid_hostname(hostname):
                return hostname
            return None
        return self._get_lb_external_address

    @property
    def _ingressed_scheme(self) -> str:
        """Return the scheme for the ingressed address.

        If upstream ingress is configured and ready, returns the upstream's scheme.
        Otherwise, returns scheme based on local TLS configuration.
        """
        if self.upstream_ingress.is_ready():
            return str(urlparse(self.upstream_ingress.url).scheme)
        return "https" if self._construct_gateway_tls_secret() is not None else "http"

    def _generate_upstream_ingress_route_configuration(self) -> Dict[str, Any]:
        """Return the scheme, host, port, and ip needed for the upstream ingress relation.

        This tells the upstream ingress provider what address, port, and scheme to use
        to route traffic to this istio-ingress gateway.
        """
        is_tls = self._construct_gateway_tls_secret() is not None
        return {
            "scheme": "https" if is_tls else "http",
            "host": self._local_gateway_address,
            "port": 443 if is_tls else 80,
            "ip": self._get_lb_external_address,
        }

    def _handle_upstream_ingress_changed(self, _):
        """Handle change in the upstream ingress relation."""
        self._sync_all_resources()

    @staticmethod
    def _generate_default_path(app_name: str, model: str) -> str:
        """Generate the default path for an ingressed route."""
        app_name = app_name.replace("/", "-")
        return f"/{model}-{app_name}"

    def _is_valid_hostname(self, hostname: Optional[str]) -> bool:
        # https://gateway-api.sigs.k8s.io/reference/spec/#gateway.networking.k8s.io/v1.Hostname
        """Check if the provided hostname is a valid DNS hostname according to RFC 1123.

        Doesn't support wildcard prefixes. This function ensures that the hostname conforms
        to the DNS naming conventions, excluding wildcards and IP addresses.

        Args:
            hostname (str): The hostname to validate.

        Returns:
            bool: True if the hostname is valid, False otherwise.
        """
        # Validate the hostname length
        if not hostname or not (1 <= len(hostname) <= 253):
            return False

        try:
            ipaddress.ip_address(hostname)
            # This is an IP address, so it is not a valid hostname
            return False
        except ValueError:
            # This is not an IP address, so it might be a valid hostname
            pass

        # Regex to match gateway hostname specs https://github.com/kubernetes-sigs/gateway-api/blob/6446fac9325dbb570675f7b85d58727096bf60a6/apis/v1/shared_types.go#L523
        # Below is the original regex used to validate hosts, as part of this dev iteration below will be omitted in favor of a regex with no wildcard support.
        # TODO: uncomment the below when support is added for both wildcards and using subdomains
        # hostname_regex = re.compile(
        #     r"^(\*\.)?[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
        # )

        # Regex with no wildcard (*) or IP support.
        hostname_regex = re.compile(
            r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
        )

        # Check if the hostname matches the required pattern
        if not hostname_regex.match(hostname):
            return False

        return True

    @property
    def _certificate_secret_name(self) -> str:
        """Return the name of the Kubernetes secret used to hold TLS certificate information."""
        return f"{self.app.name}-tls-certificate"

    def _publish_gateway_metadata(self):
        """Publish Gateway workload metadata to related charms."""
        metadata = GatewayMetadata(
            namespace=self.model.name,
            gateway_name=self.app.name,
            deployment_name=self.managed_name,
            service_account=self.managed_name,
        )
        self.gateway_metadata_provider.publish_metadata(metadata)

    @staticmethod
    def format_labels(label_dict: Dict[str, str]) -> str:
        """Format a dictionary into a comma-separated string of key=value pairs."""
        return ",".join(f"{key}={value}" for key, value in label_dict.items())


if __name__ == "__main__":
    main(IstioIngressCharm)
