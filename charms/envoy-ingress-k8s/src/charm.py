#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing Envoy Gateway ingress resources.

This charm declares the user-facing Gateway API objects (GatewayClass, Gateway,
HTTPRoute) and Envoy Gateway SecurityPolicy resources via lightkube. It has no
workload container: the Envoy Gateway control plane (envoy-controller-k8s) runs
the controller process that reconciles these objects into running Envoy proxies.
"""

# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false
# Lightkube generic resource types (create_namespaced_resource) lack proper type stubs.

import logging
from typing import Dict, List, Optional, Tuple

import ops
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    create_charm_default_labels,
)
from canonical_service_mesh.k8s.types.envoy import SecurityPolicy
from canonical_service_mesh.k8s.types.gateway_api import (
    Gateway,
    GatewayClass,
    HTTPRoute,
)
from canonical_service_mesh.models import (
    AllowedRoutes,
    BackendRef,
    GatewayTLSConfig,
    HTTPPathMatch,
    HTTPRouteMatch,
    HTTPRouteResourceSpec,
    HTTPRouteRule,
    IstioGatewaySpec,
    Listener,
    ParentRef,
    SecretObjectReference,
)
from canonical_service_mesh.models.envoy import (
    BackendObjectRef,
    ExtAuth,
    ExtAuthHTTPService,
    LocalPolicyTargetRef,
    SecurityPolicySpec,
)
from charmlibs.interfaces.gateway_metadata import GatewayMetadata, GatewayMetadataProvider
from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
from charms.oauth2_proxy_k8s.v0.forward_auth import ForwardAuthRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider
from lightkube import ApiError, Client
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Secret
from lightkube.resources.rbac_authorization_v1 import ClusterRole

logger = logging.getLogger(__name__)

# The controller name Envoy Gateway claims; the controller charm runs a manager
# that watches GatewayClasses with this exact controllerName and sets Accepted.
ENVOY_GATEWAY_CONTROLLER_NAME = "gateway.envoyproxy.io/gatewayclass-controller"

INGRESS_RELATION = "ingress"
FORWARD_AUTH_RELATION = "forward-auth"

GATEWAY_CLASS_SCOPE = "gateway-class"
GATEWAY_SCOPE = "gateway"
HTTPROUTE_SCOPE = "httproute"
SECURITY_POLICY_SCOPE = "security-policy"
TLS_SECRET_SCOPE = "gateway-tls"

HTTP_LISTENER_NAME = "http"
HTTP_PORT = 80
HTTPS_LISTENER_NAME = "https"
HTTPS_PORT = 443


class EnvoyIngressCharm(ops.CharmBase):
    """Charm for managing Envoy Gateway ingress resources."""

    def __init__(self, *args):
        super().__init__(*args)
        self._lightkube_field_manager = self.app.name
        self._lightkube_client: Optional[Client] = None

        self.ingress = IngressPerAppProvider(self, relation_name=INGRESS_RELATION)
        self.forward_auth = ForwardAuthRequirer(self)
        self.gateway_metadata = GatewayMetadataProvider(
            self, relation_name="gateway-metadata"
        )
        self.tls = TLSCertificatesRequiresV4(
            self,
            relationship_name="certificates",
            certificate_requests=[self._certificate_request],
        )

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.update_status, self._reconcile)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.tls.on.certificate_available, self._reconcile)
        self.framework.observe(self.ingress.on.data_provided, self._reconcile)
        self.framework.observe(self.ingress.on.data_removed, self._reconcile)
        self.framework.observe(self.forward_auth.on.auth_config_changed, self._reconcile)
        self.framework.observe(self.forward_auth.on.auth_config_removed, self._reconcile)
        self.framework.observe(
            self.on["gateway-metadata"].relation_changed, self._reconcile
        )

    # ---- Properties ----

    @property
    def _certificate_request(self) -> CertificateRequestAttributes:
        host = self._external_hostname or f"{self.app.name}.{self.model.name}.svc.cluster.local"
        return CertificateRequestAttributes(common_name=host, sans_dns=[host])

    @property
    def lightkube_client(self) -> Client:
        """Return a lazily-initialised lightkube client for this charm."""
        if self._lightkube_client is None:
            self._lightkube_client = Client(
                namespace=self.model.name,
                field_manager=self._lightkube_field_manager,
            )
        return self._lightkube_client

    @property
    def _external_hostname(self) -> Optional[str]:
        value = self.config.get("external_hostname")
        return str(value) if value else None

    @property
    def _tls_ready(self) -> bool:
        if not self.model.get_relation("certificates"):
            return False
        certs, key = self.tls.get_assigned_certificates()
        return bool(certs) and key is not None

    @property
    def _scheme(self) -> str:
        return "https" if self._tls_ready else "http"

    @property
    def _trusted(self) -> bool:
        """Return True when the charm has cluster-scoped permissions."""
        try:
            next(
                iter(self.lightkube_client.list(ClusterRole, labels={"nonexistent": "true"})),
                None,
            )
            return True
        except ApiError as e:
            if e.status.code in (401, 403):
                return False
            raise

    # ---- Lifecycle ----

    def _reconcile(self, _event: ops.EventBase):
        """Reconcile the whole desired state of the charm.

        Steps:
          1. Preconditions — trust. Without it no cluster writes are possible.
          2. GatewayClass — register Envoy Gateway as the Gateway API implementation.
          3. Discovery gate — wait until the controller marks the GatewayClass Accepted.
          4. TLS secret — mirror the relation cert into a K8s TLS Secret for HTTPS.
          5. Gateway — HTTP listener always, HTTPS listener when certificates are present.
          6. HTTPRoutes — one per ingress relation, dropping conflicting paths.
          7. SecurityPolicy — extAuth when forward-auth is related.
          8. Publish — ingress URLs to requirers and gateway metadata to consumers.
        """
        if not self._trusted:
            logger.warning("Charm is not trusted; skipping reconciliation")
            return

        self._reconcile_gateway_class()

        if not self._gateway_class_accepted():
            logger.info("GatewayClass not yet Accepted by the controller; waiting")
            return

        self._reconcile_tls_secret()
        self._reconcile_gateway()
        self._reconcile_httproutes()
        self._reconcile_security_policy()
        self._publish_ingress_urls()
        self._publish_gateway_metadata()

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Evaluate current state and add unit statuses."""
        if not self._trusted:
            event.add_status(
                ops.BlockedStatus(f"Trust not granted — run 'juju trust {self.app.name}'")
            )
            return
        if not self._gateway_class_accepted():
            event.add_status(
                ops.WaitingStatus("Waiting for GatewayClass controller to become available")
            )
            return
        if self._conflicting_apps():
            event.add_status(
                ops.BlockedStatus("Route conflict detected; check the logs for details")
            )
            return
        if not (address := self._gateway_address):
            event.add_status(
                ops.WaitingStatus("Waiting for gateway address assignment")
            )
            return
        event.add_status(ops.ActiveStatus(f"Serving at {address}"))

    def _on_remove(self, _event: ops.RemoveEvent):
        """Tear down cluster-scoped/app-scoped resources when the app is removed."""
        if self.app.planned_units() != 0:
            logger.info("Unit removed but application remains; leaving resources in place")
            return
        for krm in (
            self._gateway_class_krm(),
            self._gateway_krm(),
            self._httproute_krm(),
            self._security_policy_krm(),
            self._tls_secret_krm(),
        ):
            krm.delete(ignore_missing=True)

    # ---- Reconcile steps ----

    def _reconcile_gateway_class(self):
        """Create the GatewayClass that binds these resources to Envoy Gateway."""
        gateway_class = GatewayClass(
            metadata=ObjectMeta(name=self.app.name),
            spec={"controllerName": ENVOY_GATEWAY_CONTROLLER_NAME},
        )
        self._gateway_class_krm().reconcile([gateway_class])

    def _reconcile_tls_secret(self):
        """Mirror the relation certificate into a kubernetes.io/tls Secret."""
        krm = self._tls_secret_krm()
        if not self._tls_ready:
            krm.delete(ignore_missing=True)
            return
        certs, key = self.tls.get_assigned_certificates()
        secret = Secret(
            metadata=ObjectMeta(name=self._tls_secret_name, namespace=self.model.name),
            type="kubernetes.io/tls",
            stringData={
                "tls.crt": str(certs[0].certificate),
                "tls.key": str(key),
            },
        )
        krm.reconcile([secret])

    def _reconcile_gateway(self):
        """Create the Gateway with an HTTP listener, plus HTTPS when certs are present."""
        listeners = [
            Listener(
                name=HTTP_LISTENER_NAME,
                port=HTTP_PORT,
                protocol="HTTP",
                allowedRoutes=AllowedRoutes(namespaces={"from": "All"}),
                hostname=self._external_hostname,
            )
        ]
        if self._tls_ready:
            listeners.append(
                Listener(
                    name=HTTPS_LISTENER_NAME,
                    port=HTTPS_PORT,
                    protocol="HTTPS",
                    allowedRoutes=AllowedRoutes(namespaces={"from": "All"}),
                    hostname=self._external_hostname,
                    tls=GatewayTLSConfig(
                        certificateRefs=[
                            SecretObjectReference(
                                kind="Secret",
                                name=self._tls_secret_name,
                                namespace=self.model.name,
                            )
                        ]
                    ),
                )
            )
        spec = IstioGatewaySpec(gatewayClassName=self.app.name, listeners=listeners)
        gateway = Gateway(
            metadata=ObjectMeta(name=self.app.name, namespace=self.model.name),
            spec=spec.model_dump(by_alias=True, exclude_none=True),
        )
        self._gateway_krm().reconcile([gateway])

    def _reconcile_httproutes(self):
        """Create one HTTPRoute per ingress relation, dropping conflicting paths."""
        routes = []
        for relation, data in self._ready_ingress_data():
            if relation.app.name in self._conflicting_apps():
                continue
            routes.append(self._construct_httproute(relation.app.name, data))
        self._httproute_krm().reconcile(routes)

    def _reconcile_security_policy(self):
        """Manage the SecurityPolicy that applies extAuth to the Gateway."""
        krm = self._security_policy_krm()
        info = self.forward_auth.get_provider_info()
        if not info or not info.decisions_address:
            krm.delete(ignore_missing=True)
            return
        krm.reconcile([self._construct_security_policy(info.decisions_address)])

    # ---- Publish ----

    def _publish_ingress_urls(self):
        """Publish the generated ingress URL back to each (non-conflicting) requirer."""
        conflicting = self._conflicting_apps()
        host = self._gateway_address
        for relation, data in self._ready_ingress_data():
            if relation.app.name in conflicting or not host:
                self.ingress.wipe_ingress_data(relation)
                continue
            path = self._route_path(data.app.name, data.app.model)
            self.ingress.publish_url(relation, f"{self._scheme}://{host}{path}/")

    def _publish_gateway_metadata(self):
        """Publish Gateway info to gateway-metadata consumers."""
        metadata = GatewayMetadata(
            namespace=self.model.name,
            gateway_name=self.app.name,
            deployment_name=self.app.name,
            service_account=self.app.name,
        )
        self.gateway_metadata.publish_metadata(metadata)

    # ---- Construct helpers ----

    def _construct_httproute(self, app_name: str, data) -> HTTPRoute:
        """Build an HTTPRoute routing the app's default path to its backend service."""
        path = self._route_path(data.app.name, data.app.model)
        spec = HTTPRouteResourceSpec(
            parentRefs=[
                ParentRef(
                    name=self.app.name,
                    namespace=self.model.name,
                    sectionName=HTTP_LISTENER_NAME,
                )
            ],
            rules=[
                HTTPRouteRule(
                    matches=[HTTPRouteMatch(path=HTTPPathMatch(type="PathPrefix", value=path))],
                    backendRefs=[
                        BackendRef(
                            name=data.app.name,
                            namespace=data.app.model,
                            port=data.app.port,
                        )
                    ],
                )
            ],
        )
        return HTTPRoute(
            metadata=ObjectMeta(name=app_name, namespace=self.model.name),
            spec=spec.model_dump(by_alias=True, exclude_none=True),
        )

    def _construct_security_policy(self, decisions_address: str) -> SecurityPolicy:
        """Build a SecurityPolicy targeting the Gateway with extAuth at the auth backend."""
        spec = SecurityPolicySpec(
            targetRef=LocalPolicyTargetRef(
                group="gateway.networking.k8s.io",
                kind="Gateway",
                name=self.app.name,
            ),
            extAuth=ExtAuth(
                http=ExtAuthHTTPService(
                    backendRefs=[
                        BackendObjectRef(
                            group="",
                            kind="Service",
                            name=decisions_address,
                            namespace=self.model.name,
                        )
                    ]
                )
            ),
        )
        return SecurityPolicy(
            metadata=ObjectMeta(name=self.app.name, namespace=self.model.name),
            spec=spec.model_dump(by_alias=True, exclude_none=True),
        )

    # ---- Discovery + routing helpers ----

    def _gateway_class_accepted(self) -> bool:
        """Return True when the controller has marked our GatewayClass Accepted=True."""
        try:
            gc = self.lightkube_client.get(GatewayClass, name=self.app.name)
        except ApiError as e:
            if e.status.code == 404:
                return False
            raise
        status = (gc.status or {}) if hasattr(gc, "status") else {}
        conditions = status.get("conditions", []) if isinstance(status, dict) else []
        return any(
            c.get("type") == "Accepted" and c.get("status") == "True" for c in conditions
        )

    def _ready_ingress_data(self) -> List[Tuple[ops.Relation, object]]:
        """Return [(relation, IngressRequirerData)] for every ready ingress relation."""
        ready = []
        for relation in self.model.relations[INGRESS_RELATION]:
            if not self.ingress.is_ready(relation):
                continue
            ready.append((relation, self.ingress.get_data(relation)))
        return ready

    def _conflicting_apps(self) -> set:
        """Return the set of requirer app names whose route path collides with another app.

        Two requirers conflict when their generated default paths are identical but
        they are different applications. All apps sharing a contested path are dropped.
        """
        path_to_apps: Dict[str, set] = {}
        for relation, data in self._ready_ingress_data():
            path = self._route_path(data.app.name, data.app.model)
            path_to_apps.setdefault(path, set()).add(relation.app.name)
        conflicting: set = set()
        for apps in path_to_apps.values():
            if len(apps) > 1:
                conflicting |= apps
        return conflicting

    @staticmethod
    def _route_path(app_name: str, model: str) -> str:
        """Generate the default ingress path for a requirer."""
        return f"/{model}-{app_name.replace('/', '-')}"

    @property
    def _tls_secret_name(self) -> str:
        return f"{self.app.name}-tls"

    @property
    def _gateway_address(self) -> Optional[str]:
        """Return the host used in published URLs: external hostname or the LB address."""
        if self._external_hostname:
            return self._external_hostname
        try:
            gw = self.lightkube_client.get(Gateway, name=self.app.name, namespace=self.model.name)
        except ApiError:
            return None
        status = (gw.status or {}) if hasattr(gw, "status") else {}
        addresses = status.get("addresses", []) if isinstance(status, dict) else []
        for addr in addresses:
            if addr.get("value"):
                return addr["value"]
        return None

    # ---- KRM factories ----

    def _krm(self, scope: str, resource_type) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(self.app.name, self.model.name, scope=scope),
            resource_types={resource_type},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _gateway_class_krm(self) -> KubernetesResourceManager:
        return self._krm(GATEWAY_CLASS_SCOPE, GatewayClass)

    def _gateway_krm(self) -> KubernetesResourceManager:
        return self._krm(GATEWAY_SCOPE, Gateway)

    def _httproute_krm(self) -> KubernetesResourceManager:
        return self._krm(HTTPROUTE_SCOPE, HTTPRoute)

    def _security_policy_krm(self) -> KubernetesResourceManager:
        return self._krm(SECURITY_POLICY_SCOPE, SecurityPolicy)

    def _tls_secret_krm(self) -> KubernetesResourceManager:
        return self._krm(TLS_SECRET_SCOPE, Secret)


if __name__ == "__main__":
    ops.main(EnvoyIngressCharm)
