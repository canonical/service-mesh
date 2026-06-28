#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Envoy Gateway control plane."""

# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false
# Lightkube generic resource types (create_namespaced_resource) lack proper type stubs.

import base64
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import ops
import yaml
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    create_charm_default_labels,
)
from canonical_service_mesh.k8s.types.envoy import EnvoyProxy
from canonical_service_mesh.models.envoy import (
    EnvoyProxySpec,
    JSONPatchOperation,
    MetricsConfig,
    MetricSink,
    OpenTelemetrySink,
    ProxyBootstrap,
    TelemetryConfig,
)
from charmlibs.interfaces.otlp import OtlpRequirer, RuleStore
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from cosl.juju_topology import JujuTopology
from lightkube import ApiError, Client
from lightkube.models.admissionregistration_v1 import (
    MutatingWebhook,
    RuleWithOperations,
    ServiceReference,
    WebhookClientConfig,
)
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import LabelSelector, ObjectMeta
from lightkube.resources.admissionregistration_v1 import MutatingWebhookConfiguration
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import Secret, Service
from lightkube.resources.rbac_authorization_v1 import ClusterRole
from ops.pebble import Layer

logger = logging.getLogger(__name__)

SOURCE_PATH = Path(__file__).parent
CRDS_PATH = SOURCE_PATH / "crds"

GATEWAY_API_SCOPE = "gateway-api-crds"
ENVOY_GATEWAY_SCOPE = "envoy-gateway-crds"
GIE_SCOPE = "gie-crds"
AI_GATEWAY_SCOPE = "ai-gateway-crds"
WEBHOOK_SCOPE = "extproc-webhook"
ENVOY_PROXY_SCOPE = "default-envoy-proxy"
CONTROL_PLANE_SERVICE_SCOPE = "control-plane-service"

GATEWAY_CONTAINER = "envoy-gateway"
AI_GATEWAY_CONTAINER = "ai-gateway"

# Envoy Gateway hardcodes the control-plane name "envoy-gateway" in the proxy
# bootstrap: proxies dial the xDS server at envoy-gateway.<ns>.svc:18000, and
# certgen names the control-plane server-cert Secret "envoy-gateway" too. So the
# charm must publish a Service of exactly this name and serve that Secret's cert.
CONTROL_PLANE_NAME = "envoy-gateway"
XDS_PORT = 18000
WASM_PORT = 18002

EXTENSION_SERVER_PORT = 1063
WEBHOOK_PORT = 9443
# The AI Gateway controller looks up its ExtProc webhook by this exact name
# (`<name>.<namespace>`) at startup and exits if it is missing — see
# maybePatchAdmissionWebhook in cmd/controller/main.go. Must not be renamed.
MUTATING_WEBHOOK_NAME = "envoy-ai-gateway-gateway-pod-mutator"

# Upstream component versions baked into this charm revision.
# The charm track mirrors the Envoy Gateway minor version (e.g. 1.6/stable).
# TODO: enforce sequential minor-version upgrades on upgrade-charm.
#       See Discussion Points in specs/envoy.spec.md.
ENVOY_GATEWAY_VERSION = "1.7.0"
AI_GATEWAY_VERSION = "0.6.0"
GATEWAY_API_VERSION = "1.4.1"
GIE_VERSION = "1.3.0"
# ExtProc sidecar image the AI Gateway controller injects; pin to the controller
# version so it never falls back to the upstream ':latest' default.
EXTPROC_IMAGE = f"docker.io/envoyproxy/ai-gateway-extproc:v{AI_GATEWAY_VERSION}"


def _load_crd_yaml(directory: str) -> list:
    """Load all CRD YAML documents from crds/<directory>/*.yaml."""
    from lightkube.codecs import load_all_yaml

    crd_dir = CRDS_PATH / directory
    if not crd_dir.exists():
        return []
    docs = []
    for yaml_file in sorted(crd_dir.glob("*.yaml")):
        docs.extend(load_all_yaml(yaml_file.read_text(), create_resources_for_crds=False))
    return docs


class _CrdsNotEstablishedError(Exception):
    """Raised when one or more CRDs have been applied but not yet Established."""


class EnvoyControllerCharm(ops.CharmBase):
    """Charm for managing the Envoy Gateway control plane."""

    def __init__(self, *args):
        super().__init__(*args)
        self._lightkube_field_manager = self.app.name
        self._lightkube_client: Optional[Client] = None

        _rules = RuleStore(JujuTopology.from_charm(self)).add_promql_path(
            SOURCE_PATH / "prometheus_alert_rules"
        )
        self.otlp = OtlpRequirer(
            self,
            relation_name="otlp",
            protocols=["http"],
            telemetries=["metrics"],
            rules=_rules,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.update_status, self._reconcile)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.envoy_gateway_pebble_ready, self._reconcile)
        self.framework.observe(self.on.ai_gateway_pebble_ready, self._reconcile)
        self.framework.observe(self.on["otlp"].relation_changed, self._reconcile)
        self.framework.observe(self.on["otlp"].relation_broken, self._reconcile)

    # ---- Properties ----

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
    def _ai_enabled(self) -> bool:
        return bool(self.config["enable-ai-gateway"])

    @property
    def _log_level(self) -> str:
        return str(self.config["log-level"])

    @property
    def _otlp_endpoint(self) -> Optional[str]:
        """Return the first OTLP endpoint URL from the relation, or None."""
        for ep in self.otlp.endpoints.values():
            return ep.endpoint
        return None

    def _otlp_metric_sink(self) -> Optional[MetricSink]:
        """Return an Envoy OpenTelemetry MetricSink for the OTLP endpoint, or None.

        The OTLP relation provides a URL (e.g. ``http://collector:4318``); Envoy
        Gateway's metric sink expects a host and port, so the URL is parsed here.
        """
        endpoint = self._otlp_endpoint
        if not endpoint:
            return None
        parsed = urlparse(endpoint)
        if not parsed.hostname:
            return None
        return MetricSink(
            openTelemetry=OpenTelemetrySink(
                host=parsed.hostname,
                port=parsed.port or 4318,
            )
        )

    def _control_plane_secret(self) -> Optional[Secret]:
        """Return the certgen-issued control-plane TLS Secret, or None if absent.

        certgen names this Secret ``envoy-gateway``; it holds the server cert the
        xDS/webhook servers present and the CA proxies validate against. lightkube
        returns ``data`` already base64-encoded (the Secret wire format).
        """
        try:
            return self.lightkube_client.get(
                Secret, name=CONTROL_PLANE_NAME, namespace=self.model.name
            )
        except ApiError as e:
            if e.status.code == 404:
                return None
            raise

    @property
    def _ca_bundle(self) -> str:
        # K8s webhook caBundle is a []byte field: base64-encoded PEM. The Secret's
        # ca.crt is already base64(PEM), so it is the caBundle value verbatim.
        secret = self._control_plane_secret()
        if not secret or not secret.data:
            return ""
        return secret.data.get("ca.crt", "")

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
        """Reconcile the entire state of the charm.

        Steps:
          0. Publish observability — Grafana dashboards and OTLP alert rules are pure
             databag operations; publish them unconditionally so they are available
             even when other preconditions are not yet met.
          1. Check preconditions — trust and Pebble. Any unmet precondition halts
             reconciliation; status is set via _on_collect_status.
          2. Apply CRDs — Gateway API and GIE always; AI Gateway CRDs only when enabled.
          3. Run certgen — mint the control-plane mTLS secrets; must precede the cert
             push, which serves the certgen-issued cert.
          4. Push config and certs — controller config YAML and the certgen control-plane
             cert into containers.
          5. Reconcile control-plane Service — the "envoy-gateway" Service proxies and the
             API server dial for xDS (and, when AI is on, the webhook/extension server).
          6. Reconcile webhook — create/remove ExtProc MutatingWebhookConfiguration.
          7. Reconcile EnvoyProxy — default resource with Juju-topology stats tags and OTLP sink.
          8. Reconcile Pebble services — add layers and replan; stop AI Gateway when disabled.
        """
        # Step 0: observability — no cluster access needed
        self.grafana_dashboards.update_dashboards()
        self.otlp.publish()

        # Step 1: preconditions
        if not self._trusted:
            logger.warning("Charm is not trusted; skipping reconciliation")
            return
        if not self.unit.get_container(GATEWAY_CONTAINER).can_connect():
            logger.info("Pebble not ready; skipping reconciliation")
            return

        # Step 2: CRDs — raises _CrdsNotEstablishedError if API server not ready yet
        try:
            self._reconcile_crds()
        except _CrdsNotEstablishedError:
            logger.info("CRDs applied but not yet Established; deferring controller start")
            return
        # Step 3: control-plane certs (must run before the cert push below)
        self._reconcile_certgen()
        # Step 4: config + certs
        self._reconcile_config_and_certs()
        # Step 5: control-plane Service
        self._reconcile_control_plane_service()
        # Step 6: webhook
        self._reconcile_webhook()
        # Step 7: default EnvoyProxy
        self._reconcile_envoy_proxy()
        # Step 8: Pebble services
        self._reconcile_pebble_services()

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Evaluate current state and add unit statuses."""
        if not self._trusted:
            event.add_status(
                ops.BlockedStatus(f"Trust not granted. Run 'juju trust {self.app.name}'")
            )
            return
        if not self.unit.get_container(GATEWAY_CONTAINER).can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble (envoy-gateway container)"))
            return
        for container_name, service in [
            (GATEWAY_CONTAINER, "envoy-gateway"),
            (AI_GATEWAY_CONTAINER, "ai-gateway"),
        ]:
            if container_name == AI_GATEWAY_CONTAINER and not self._ai_enabled:
                continue
            container = self.unit.get_container(container_name)
            if not container.can_connect():
                event.add_status(
                    ops.WaitingStatus(f"Waiting for Pebble ({container_name} container)")
                )
                return
            if not self._container_healthy(container, service):
                event.add_status(
                    ops.WaitingStatus(f"Waiting for {service} controller to become healthy")
                )
                return
        event.add_status(ops.ActiveStatus())

    def _on_remove(self, _event: ops.RemoveEvent):
        """Remove app-scoped resources on app removal. CRDs are left in place.

        The ExtProc webhook and the xDS Service are app-scoped (not Juju-managed),
        so they must only be removed when the whole application is going away
        (planned_units == 0), not on a scale-down where peer units still rely on
        them. KRM swallows the expected 404 via ignore_missing; any other API error
        is allowed to surface.
        """
        if self.app.planned_units() != 0:
            logger.info("Unit removed but application remains; leaving resources in place")
            return
        self._webhook_krm().delete(ignore_missing=True)
        self._control_plane_service_krm().delete(ignore_missing=True)

    # ---- Reconcile steps ----

    def _reconcile_crds(self):
        """Apply Gateway API + Envoy Gateway + GIE CRDs always; AI Gateway CRDs conditionally.

        After applying, waits for all CRDs to reach Established=True before
        returning so that controllers do not start against unregistered schemas.
        """
        self._crd_krm(GATEWAY_API_SCOPE).reconcile(_load_crd_yaml("gateway-api"))
        self._crd_krm(ENVOY_GATEWAY_SCOPE).reconcile(_load_crd_yaml("envoy-gateway"))
        self._crd_krm(GIE_SCOPE).reconcile(_load_crd_yaml("gie"))
        if self._ai_enabled:
            self._crd_krm(AI_GATEWAY_SCOPE).reconcile(_load_crd_yaml("ai-gateway"))
        else:
            self._crd_krm(AI_GATEWAY_SCOPE).delete(ignore_missing=True)

        if not self._crds_established():
            raise _CrdsNotEstablishedError()

    def _reconcile_config_and_certs(self):
        """Push controller config and the certgen control-plane cert into containers.

        Envoy Gateway reads its xDS-server TLS from ``/certs/{tls.crt,tls.key,ca.crt}``,
        and the AI Gateway controller defaults its webhook server to the same path. The
        cert MUST be the certgen ``envoy-gateway`` Secret: Envoy Proxy pods are wired by
        Envoy Gateway to trust the certgen CA, so a cert from any other CA fails the
        proxy<->control-plane mTLS handshake. certgen (step 3) runs first, so the Secret
        exists by now; if it somehow does not, skip rather than serve a wrong cert.
        """
        secret = self._control_plane_secret()
        if not secret or not secret.data:
            logger.info("Control-plane cert Secret not present yet; skipping cert push")
            return
        cert_pem = base64.b64decode(secret.data["tls.crt"]).decode()
        key_pem = base64.b64decode(secret.data["tls.key"]).decode()
        ca_pem = base64.b64decode(secret.data["ca.crt"]).decode()

        extension_fqdn = (
            f"{CONTROL_PLANE_NAME}.{self.model.name}.svc.cluster.local"
            if self._ai_enabled
            else None
        )
        self._push_files(
            GATEWAY_CONTAINER,
            {
                "/etc/envoy-gateway/config.yaml": self._construct_envoy_gateway_config(
                    extension_manager_fqdn=extension_fqdn,
                ),
                "/certs/tls.crt": cert_pem,
                "/certs/tls.key": key_pem,
                "/certs/ca.crt": ca_pem,
            },
        )
        if self._ai_enabled:
            self._push_files(
                AI_GATEWAY_CONTAINER,
                {
                    "/certs/tls.crt": cert_pem,
                    "/certs/tls.key": key_pem,
                    "/certs/ca.crt": ca_pem,
                },
            )

    def _reconcile_control_plane_service(self):
        """Publish the Service clients use to reach the control plane.

        Envoy Gateway hardcodes the proxy bootstrap to dial ``envoy-gateway.<ns>.svc``
        on the xDS (18000) and wasm (18002) ports — names its own Helm chart supplies.
        The charm app Service is named after the app, so without this Service the proxy
        DNS lookup yields no endpoints ("no healthy upstream") and Gateways never reach
        Programmed=True. When AI Gateway is enabled the same Service also fronts the
        ExtProc webhook (9443) and Extension Server (1063): the certgen control-plane
        cert's SANs are ``envoy-gateway.*``, so callers must dial this name for the TLS
        handshake to validate.
        """
        self._control_plane_service_krm().reconcile([self._construct_control_plane_service()])

    def _construct_control_plane_service(self) -> Service:
        """Construct the ``envoy-gateway`` Service selecting the controller pods."""
        ports = [
            ServicePort(name="xds", port=XDS_PORT, targetPort=XDS_PORT),
            ServicePort(name="wasm", port=WASM_PORT, targetPort=WASM_PORT),
        ]
        if self._ai_enabled:
            ports.append(ServicePort(name="webhook", port=WEBHOOK_PORT, targetPort=WEBHOOK_PORT))
            ports.append(
                ServicePort(
                    name="extension", port=EXTENSION_SERVER_PORT, targetPort=EXTENSION_SERVER_PORT
                )
            )
        return Service(
            metadata=ObjectMeta(name=CONTROL_PLANE_NAME, namespace=self.model.name),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": self.app.name},
                ports=ports,
            ),
        )

    def _reconcile_webhook(self):
        """Manage the ExtProc MutatingWebhookConfiguration."""
        krm = self._webhook_krm()
        if not self._ai_enabled:
            krm.delete(ignore_missing=True)
            return
        krm.reconcile([self._construct_extproc_webhook()])

    def _reconcile_envoy_proxy(self):
        """Manage the default EnvoyProxy resource (stats tags + OTLP sink)."""
        self._envoy_proxy_krm().reconcile([self._construct_envoy_proxy()])

    def _reconcile_certgen(self):
        """Provision the control-plane secrets Envoy Gateway requires via its certgen.

        Upstream ships a one-shot ``certgen`` Job that mints the control-plane mTLS
        secrets (``envoy``, ``envoy-gateway``, ``envoy-rate-limit``) and the
        ``envoy-oidc-hmac`` secret that the OAuth2 filter signs OIDC state/session
        cookies with. Without these the controller blocks on a missing ``envoy``
        secret and never serves xDS. We have no Job, so we run certgen in-place in
        the gateway container. It is idempotent — existing secrets are left untouched
        (no ``--overwrite``) so values stay stable across reconciles and scaled units.
        ``--disable-topology-injector`` stops certgen from patching an unrelated
        injector webhook. ``ENVOY_GATEWAY_NAMESPACE`` must be set or certgen targets
        the non-existent default ``envoy-gateway-system`` namespace.
        """
        container = self.unit.get_container(GATEWAY_CONTAINER)
        container.exec(
            ["envoy-gateway", "certgen", "--disable-topology-injector"],
            environment={"ENVOY_GATEWAY_NAMESPACE": self.model.name},
        ).wait()

    def _reconcile_pebble_services(self):
        """Add Pebble layers and replan controller services."""
        gateway = self.unit.get_container(GATEWAY_CONTAINER)
        gateway.add_layer("envoy-gateway", self._construct_gateway_layer(), combine=True)
        gateway.replan()

        ai = self.unit.get_container(AI_GATEWAY_CONTAINER)
        if not ai.can_connect():
            return
        if self._ai_enabled:
            ai.add_layer("ai-gateway", self._construct_ai_gateway_layer(), combine=True)
            ai.replan()
        else:
            if "ai-gateway" in ai.get_plan().services:
                ai.stop("ai-gateway")

    # ---- Construct helpers ----

    def _construct_envoy_gateway_config(self, *, extension_manager_fqdn: Optional[str]) -> str:
        """Construct the Envoy Gateway controller config YAML."""
        envoy_gateway: dict[str, Any] = {
            "logging": {"level": {"default": self._log_level}},
            "extensionApis": {
                "enableEnvoyPatchPolicy": True,
                "enableBackend": True,
            },
        }
        if extension_manager_fqdn:
            envoy_gateway["extensionManager"] = {
                "hooks": {
                    "xdsTranslator": {
                        "post": ["HTTPListener", "Route", "Cluster", "Secret"],
                    }
                },
                "service": {
                    "fqdn": {
                        "hostname": extension_manager_fqdn,
                        "port": EXTENSION_SERVER_PORT,
                    }
                },
            }
        sink = self._otlp_metric_sink()
        if sink:
            telemetry = TelemetryConfig(metrics=MetricsConfig(sinks=[sink]))
            envoy_gateway["telemetry"] = telemetry.model_dump(by_alias=True, exclude_none=True)
        return yaml.safe_dump(
            {
                "apiVersion": "gateway.envoyproxy.io/v1alpha1",
                "kind": "EnvoyGateway",
                "envoyGateway": envoy_gateway,
            }
        )

    def _construct_envoy_proxy(self) -> EnvoyProxy:
        """Construct the default EnvoyProxy resource (Juju-topology stats tags + OTLP sink).

        EnvoyProxy has no native stats-tags field, so the Juju topology is stamped onto
        every proxy metric by JSON-patching the Envoy bootstrap's stats_config.stats_tags.
        """
        topology = {
            "juju_model": self.model.name,
            "juju_model_uuid": self.model.uuid,
            "juju_application": self.app.name,
            "juju_charm": self.meta.name,
        }
        stats_tag_patches = [
            JSONPatchOperation(
                op="add",
                path="/stats_config/stats_tags/-",
                value={"tag_name": name, "fixed_value": value},
            )
            for name, value in topology.items()
        ]
        sink = self._otlp_metric_sink()
        telemetry = TelemetryConfig(metrics=MetricsConfig(sinks=[sink])) if sink else None
        spec = EnvoyProxySpec(
            bootstrap=ProxyBootstrap(type="JSONPatch", jsonPatches=stats_tag_patches),
            telemetry=telemetry,
        )
        return EnvoyProxy(
            metadata=ObjectMeta(name=self.app.name, namespace=self.model.name),
            spec=spec.model_dump(by_alias=True, exclude_none=True),
        )

    def _crds_established(self) -> bool:
        """Return True when all managed CRDs have Established=True in their status."""
        scopes = [GATEWAY_API_SCOPE, ENVOY_GATEWAY_SCOPE, GIE_SCOPE]
        if self._ai_enabled:
            scopes.append(AI_GATEWAY_SCOPE)
        for scope in scopes:
            try:
                resources = self._crd_krm(scope).get_deployed_resources()
            except ApiError:
                return False
            for crd in resources:
                conditions = (crd.status.conditions or []) if crd.status else []
                established = any(
                    c.type == "Established" and c.status == "True" for c in conditions
                )
                if not established:
                    logger.debug("CRD %s not yet Established", crd.metadata.name)
                    return False
        return True

    def _construct_extproc_webhook(self) -> MutatingWebhookConfiguration:
        """Construct the ExtProc sidecar-injector MutatingWebhookConfiguration."""
        return MutatingWebhookConfiguration(
            metadata=ObjectMeta(name=f"{MUTATING_WEBHOOK_NAME}.{self.model.name}"),
            webhooks=[
                MutatingWebhook(
                    name="ai-gateway-extproc.envoyproxy.io",
                    clientConfig=WebhookClientConfig(
                        service=ServiceReference(
                            name=CONTROL_PLANE_NAME,
                            namespace=self.model.name,
                            port=WEBHOOK_PORT,
                            path="/mutate",
                        ),
                        caBundle=self._ca_bundle,
                    ),
                    rules=[
                        RuleWithOperations(
                            apiGroups=[""],
                            apiVersions=["v1"],
                            operations=["CREATE"],
                            resources=["pods"],
                        )
                    ],
                    objectSelector=LabelSelector(
                        matchLabels={"app.kubernetes.io/managed-by": "envoy-gateway"}
                    ),
                    failurePolicy="Fail",
                    timeoutSeconds=10,
                    sideEffects="None",
                    admissionReviewVersions=["v1"],
                )
            ],
        )

    def _construct_gateway_layer(self) -> Layer:
        """Construct the Pebble layer for the Envoy Gateway controller."""
        return Layer(
            {
                "summary": "Envoy Gateway",
                "description": "Envoy Gateway controller",
                "services": {
                    "envoy-gateway": {
                        "override": "replace",
                        "summary": "Envoy Gateway controller",
                        "command": "envoy-gateway server --config-path /etc/envoy-gateway/config.yaml",
                        "startup": "enabled",
                        "environment": {"ENVOY_GATEWAY_NAMESPACE": self.model.name},
                        "on-check-failure": {"liveness": "restart"},
                    }
                },
                "checks": {
                    "liveness": {
                        "override": "replace",
                        "level": "alive",
                        "http": {"url": "http://localhost:8081/healthz"},
                    },
                    "readiness": {
                        "override": "replace",
                        "level": "ready",
                        "http": {"url": "http://localhost:8081/readyz"},
                    },
                },
            }
        )

    def _construct_ai_gateway_layer(self) -> Layer:
        """Construct the Pebble layer for the AI Gateway controller.

        The image ENTRYPOINT is ``/app`` (the controller binary); it takes flags,
        not a config file. TLS defaults (``--tlsCertDir=/certs``, ``tls.crt``/
        ``tls.key``/``ca.crt``) match the certs pushed in ``_reconcile_config_and_certs``.
        Health is a gRPC probe upstream; Pebble has no gRPC check, so we TCP-probe
        the extension-server port instead.
        """
        command = " ".join(
            [
                "/app",
                f"-logLevel={self._log_level}",
                f"--extProcImage={EXTPROC_IMAGE}",
                f"--extProcLogLevel={self._log_level}",
                f"--webhookPort={WEBHOOK_PORT}",
            ]
        )
        return Layer(
            {
                "summary": "AI Gateway",
                "description": "AI Gateway controller",
                "services": {
                    "ai-gateway": {
                        "override": "replace",
                        "summary": "AI Gateway controller",
                        "command": command,
                        "startup": "enabled",
                        "environment": {"POD_NAMESPACE": self.model.name},
                        "on-check-failure": {"liveness": "restart"},
                    }
                },
                "checks": {
                    "liveness": {
                        "override": "replace",
                        "level": "alive",
                        "tcp": {"port": EXTENSION_SERVER_PORT},
                    },
                    "readiness": {
                        "override": "replace",
                        "level": "ready",
                        "tcp": {"port": EXTENSION_SERVER_PORT},
                    },
                },
            }
        )

    # ---- Helpers ----

    def _push_files(self, container_name: str, files: dict[str, str]):
        """Push a map of path -> content into a container."""
        container = self.unit.get_container(container_name)
        if not container.can_connect():
            return
        for path, content in files.items():
            container.push(path, content, make_dirs=True)

    @staticmethod
    def _container_healthy(container: ops.Container, service_name: str) -> bool:
        """Return True if the named service has no failing ready-level checks."""
        plan = container.get_plan()
        if service_name not in plan.services:
            return True
        try:
            checks = container.get_checks(level=ops.pebble.CheckLevel.READY)
        except ops.pebble.Error:
            return True
        return all(c.status == ops.pebble.CheckStatus.UP for c in checks.values())

    # ---- KRM factories ----

    def _crd_krm(self, scope: str) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(self.app.name, self.model.name, scope=scope),
            resource_types={CustomResourceDefinition},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _webhook_krm(self) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=WEBHOOK_SCOPE
            ),
            resource_types={MutatingWebhookConfiguration},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _envoy_proxy_krm(self) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=ENVOY_PROXY_SCOPE
            ),
            resource_types={EnvoyProxy},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _control_plane_service_krm(self) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=CONTROL_PLANE_SERVICE_SCOPE
            ),
            resource_types={Service},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )


if __name__ == "__main__":
    ops.main(EnvoyControllerCharm)
