#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Envoy Gateway control plane."""

# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false
# Lightkube generic resource types (create_namespaced_resource) lack proper type stubs.

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
    BootstrapConfig,
    EnvoyProxySpec,
    MetricsConfig,
    MetricSink,
    OpenTelemetrySink,
    StatsTag,
    TelemetryConfig,
)
from charmlibs.interfaces.otlp import OtlpRequirer, RuleStore
from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from cosl.juju_topology import JujuTopology
from lightkube import ApiError, Client
from lightkube.models.admissionregistration_v1 import (
    MutatingWebhook,
    RuleWithOperations,
    ServiceReference,
    WebhookClientConfig,
)
from lightkube.models.meta_v1 import LabelSelector, ObjectMeta
from lightkube.resources.admissionregistration_v1 import MutatingWebhookConfiguration
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.rbac_authorization_v1 import ClusterRole
from ops.pebble import Layer

logger = logging.getLogger(__name__)

SOURCE_PATH = Path(__file__).parent
CRDS_PATH = SOURCE_PATH.parent / "crds"

GATEWAY_API_SCOPE = "gateway-api-crds"
GIE_SCOPE = "gie-crds"
AI_GATEWAY_SCOPE = "ai-gateway-crds"
WEBHOOK_SCOPE = "extproc-webhook"
ENVOY_PROXY_SCOPE = "default-envoy-proxy"

GATEWAY_CONTAINER = "envoy-gateway"
AI_GATEWAY_CONTAINER = "ai-gateway"

ENVOY_PROXY_NAME = "envoy-default"
ENVOY_PROXY_NAMESPACE = "envoy-gateway-system"
EXTENSION_SERVER_PORT = 1063
WEBHOOK_PORT = 9443

# Upstream component versions baked into this charm revision.
# The charm track mirrors the Envoy Gateway minor version (e.g. 1.6/stable).
# TODO: enforce sequential minor-version upgrades on upgrade-charm.
#       See Discussion Points in specs/envoy.spec.md.
ENVOY_GATEWAY_VERSION = "1.6.3"
AI_GATEWAY_VERSION = "0.5.0"
GATEWAY_API_VERSION = "1.4.1"
GIE_VERSION = "1.3.0"


def _cert_sans(app_name: str, model_name: str) -> list[str]:
    """DNS SANs for the webhook + extension server certificate."""
    return [
        f"{app_name}.{model_name}.svc.cluster.local",
        f"{app_name}.{model_name}.svc",
        f"{app_name}.{model_name}",
        app_name,
    ]


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

        self.tls = TLSCertificatesRequiresV4(
            self,
            relationship_name="certificates",
            certificate_requests=[
                CertificateRequestAttributes(
                    common_name=f"{self.app.name}.{self.model.name}.svc.cluster.local",
                    sans_dns=_cert_sans(self.app.name, self.model.name),
                )
            ],
        )
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
        self.framework.observe(self.on.secret_changed, self._reconcile)
        self.framework.observe(self.on.secret_expired, self._reconcile)
        self.framework.observe(self.tls.on.certificate_available, self._reconcile)
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

    @property
    def _ca_bundle(self) -> str:
        certs, _ = self.tls.get_assigned_certificates()
        return str(certs[0].ca) if certs else ""

    @property
    def _tls_ready(self) -> bool:
        certs, key = self.tls.get_assigned_certificates()
        return bool(certs) and key is not None

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
          1. Check preconditions — trust, certificates relation, Pebble, TLS cert issuance.
             Any unmet precondition halts reconciliation; status is set via _on_collect_status.
          2. Apply CRDs — Gateway API and GIE always; AI Gateway CRDs only when enabled.
          3. Push config and certs — controller config YAML and TLS material into containers.
          4. Reconcile webhook — create/remove ExtProc MutatingWebhookConfiguration.
          5. Reconcile EnvoyProxy — default resource with Juju-topology stats tags and OTLP sink.
          6. Reconcile Pebble services — add layers and replan; stop AI Gateway when disabled.
        """
        # Step 0: observability — no cluster access or TLS needed
        self.grafana_dashboards.update_dashboards()
        self.otlp.publish()

        # Step 1: preconditions
        if not self._trusted:
            logger.warning("Charm is not trusted; skipping reconciliation")
            return
        if not self.model.get_relation("certificates"):
            logger.info("No certificates relation; skipping reconciliation")
            return
        if not self.unit.get_container(GATEWAY_CONTAINER).can_connect():
            logger.info("Pebble not ready; skipping reconciliation")
            return
        if not self._tls_ready:
            logger.info("TLS certificates not yet available; skipping reconciliation")
            return

        # Step 2: CRDs — raises _CrdsNotEstablishedError if API server not ready yet
        try:
            self._reconcile_crds()
        except _CrdsNotEstablishedError:
            logger.info("CRDs applied but not yet Established; deferring controller start")
            return
        # Step 3: config + certs
        self._reconcile_config_and_certs()
        # Step 4: webhook
        self._reconcile_webhook()
        # Step 5: default EnvoyProxy
        self._reconcile_envoy_proxy()
        # Step 6: Pebble services
        self._reconcile_pebble_services()

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Evaluate current state and add unit statuses."""
        if not self._trusted:
            event.add_status(
                ops.BlockedStatus(f"Trust not granted. Run 'juju trust {self.app.name}'")
            )
            return
        if not self.model.get_relation("certificates"):
            event.add_status(ops.BlockedStatus("Missing relation: certificates"))
            return
        if not self.unit.get_container(GATEWAY_CONTAINER).can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble (envoy-gateway container)"))
            return
        if not self._tls_ready:
            event.add_status(ops.WaitingStatus("Waiting for TLS certificates"))
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
        """Remove the ExtProc webhook on app removal. CRDs are left in place.

        The webhook is app-scoped, so it must only be removed when the whole
        application is going away (planned_units == 0), not on a scale-down where
        peer units still rely on it. KRM swallows the expected 404 via
        ignore_missing; any other API error is allowed to surface.
        """
        if self.app.planned_units() != 0:
            logger.info("Unit removed but application remains; leaving webhook in place")
            return
        self._webhook_krm().delete(ignore_missing=True)

    # ---- Reconcile steps ----

    def _reconcile_crds(self):
        """Apply Gateway API + GIE CRDs always; AI Gateway CRDs conditionally.

        After applying, waits for all CRDs to reach Established=True before
        returning so that controllers do not start against unregistered schemas.
        """
        self._crd_krm(GATEWAY_API_SCOPE).reconcile(_load_crd_yaml("gateway-api"))
        self._crd_krm(GIE_SCOPE).reconcile(_load_crd_yaml("gie"))
        if self._ai_enabled:
            self._crd_krm(AI_GATEWAY_SCOPE).reconcile(_load_crd_yaml("ai-gateway"))
        else:
            self._crd_krm(AI_GATEWAY_SCOPE).delete(ignore_missing=True)

        if not self._crds_established():
            raise _CrdsNotEstablishedError()

    def _reconcile_config_and_certs(self):
        """Push controller config files and TLS material into containers."""
        certs, key = self.tls.get_assigned_certificates()
        if not certs or key is None:
            return
        cert_pem = str(certs[0].certificate)
        ca_pem = str(certs[0].ca)
        key_pem = str(key)

        extension_fqdn = (
            f"{self.app.name}.{self.model.name}.svc.cluster.local" if self._ai_enabled else None
        )
        self._push_files(
            GATEWAY_CONTAINER,
            {
                "/etc/envoy-gateway/config.yaml": self._construct_envoy_gateway_config(
                    extension_manager_fqdn=extension_fqdn,
                ),
                "/etc/envoy-gateway/tls/tls.crt": cert_pem,
                "/etc/envoy-gateway/tls/tls.key": key_pem,
                "/etc/envoy-gateway/tls/ca.crt": ca_pem,
            },
        )
        if self._ai_enabled:
            self._push_files(
                AI_GATEWAY_CONTAINER,
                {
                    "/etc/ai-gateway/config.yaml": yaml.safe_dump({"logLevel": self._log_level}),
                    "/etc/ai-gateway/tls/tls.crt": cert_pem,
                    "/etc/ai-gateway/tls/tls.key": key_pem,
                    "/etc/ai-gateway/tls/ca.crt": ca_pem,
                },
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
        """Construct the default EnvoyProxy resource (Juju-topology stats tags + OTLP sink)."""
        stats_tags = [
            StatsTag(tagName="juju_model", fixedValue=self.model.name),
            StatsTag(tagName="juju_model_uuid", fixedValue=self.model.uuid),
            StatsTag(tagName="juju_application", fixedValue=self.app.name),
            StatsTag(tagName="juju_charm", fixedValue=self.meta.name),
        ]
        sink = self._otlp_metric_sink()
        telemetry = TelemetryConfig(metrics=MetricsConfig(sinks=[sink])) if sink else None
        spec = EnvoyProxySpec(
            bootstrap=BootstrapConfig(statsTags=stats_tags),
            telemetry=telemetry,
        )
        return EnvoyProxy(
            metadata=ObjectMeta(name=ENVOY_PROXY_NAME, namespace=ENVOY_PROXY_NAMESPACE),
            spec=spec.model_dump(by_alias=True, exclude_none=True),
        )

    def _crds_established(self) -> bool:
        """Return True when all managed CRDs have Established=True in their status."""
        scopes = [GATEWAY_API_SCOPE, GIE_SCOPE]
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
            metadata=ObjectMeta(name=f"{self.app.name}-{self.model.name}-extproc"),
            webhooks=[
                MutatingWebhook(
                    name="ai-gateway-extproc.envoyproxy.io",
                    clientConfig=WebhookClientConfig(
                        service=ServiceReference(
                            name=self.app.name,
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
                        "on-check-failure": {"liveness": "restart"},
                    }
                },
                "checks": {
                    "liveness": {
                        "override": "replace",
                        "level": "alive",
                        "http": {"url": "http://localhost:19001/healthz"},
                    },
                    "readiness": {
                        "override": "replace",
                        "level": "ready",
                        "http": {"url": "http://localhost:19001/readyz"},
                    },
                },
            }
        )

    def _construct_ai_gateway_layer(self) -> Layer:
        """Construct the Pebble layer for the AI Gateway controller."""
        return Layer(
            {
                "summary": "AI Gateway",
                "description": "AI Gateway controller",
                "services": {
                    "ai-gateway": {
                        "override": "replace",
                        "summary": "AI Gateway controller",
                        "command": "ai-gateway-controller --config-path /etc/ai-gateway/config.yaml",
                        "startup": "enabled",
                        "on-check-failure": {"liveness": "restart"},
                    }
                },
                "checks": {
                    "liveness": {
                        "override": "replace",
                        "level": "alive",
                        "http": {"url": "http://localhost:19002/healthz"},
                    },
                    "readiness": {
                        "override": "replace",
                        "level": "ready",
                        "http": {"url": "http://localhost:19002/readyz"},
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


if __name__ == "__main__":
    ops.main(EnvoyControllerCharm)
