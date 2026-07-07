#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Envoy Gateway control plane."""

# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false
# Lightkube generic resource types (create_namespaced_resource) lack proper type stubs.

import base64
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import ops
import yaml
from canonical_service_mesh.interfaces.envoy_extension_server import ExtensionServerRequirer
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    create_charm_default_labels,
)
from canonical_service_mesh.k8s.types.envoy import EnvoyProxy
from canonical_service_mesh.k8s.types.gateway_api import GatewayClass
from canonical_service_mesh.models import GatewayClassSpec, ParametersRef
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
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from cosl.juju_topology import JujuTopology
from lightkube import ApiError, Client
from lightkube.codecs import load_all_yaml
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import Secret, Service
from lightkube.resources.rbac_authorization_v1 import ClusterRole
from ops.pebble import ExecError, Layer

logger = logging.getLogger(__name__)

SOURCE_PATH = Path(__file__).parent
CRDS_PATH = SOURCE_PATH / "crds"

GATEWAY_API_SCOPE = "gateway-api-crds"
ENVOY_GATEWAY_SCOPE = "envoy-gateway-crds"
GIE_SCOPE = "gie-crds"
ENVOY_PROXY_SCOPE = "default-envoy-proxy"
CONTROL_PLANE_SERVICE_SCOPE = "control-plane-service"
GATEWAY_CLASS_SCOPE = "gateway-class"

# The single, cluster-scoped GatewayClass this charm owns. Ingress charms only reference
# it (gatewayClassName) — they never create it — so the name is hardcoded on both charms
# as the cross-charm contract (there is no relation). Its parametersRef points at the
# default EnvoyProxy below, so every proxy inherits the OTLP sink + Juju-topology tags.
GATEWAY_CLASS_NAME = "envoy"
# KRM stamps this instance label (=<model>-<app>) on every resource it manages, so the
# "envoy" class we create carries our identity while one from another charm or a non-Juju
# install (Helm/kubectl) does not. Reading it back tells "the class we manage" apart from
# a foreign one — the class is a cluster-wide singleton, so we block on a foreign one.
GATEWAY_CLASS_OWNER_LABEL = "app.kubernetes.io/instance"
ENVOY_GATEWAY_CONTROLLER_NAME = "gateway.envoyproxy.io/gatewayclass-controller"
ENVOY_PROXY_GROUP = "gateway.envoyproxy.io"
ENVOY_PROXY_KIND = "EnvoyProxy"

# CRD reconcile scope -> the crds/<dir> the bundle is loaded from.
CRD_SCOPES = {
    GATEWAY_API_SCOPE: "gateway-api",
    ENVOY_GATEWAY_SCOPE: "envoy-gateway",
    GIE_SCOPE: "gie",
}

GATEWAY_CONTAINER = "envoy-gateway"

# Envoy Gateway hardcodes the control-plane name "envoy-gateway" in the proxy
# bootstrap: proxies dial the xDS server at envoy-gateway.<ns>.svc:18000, and
# certgen names the control-plane server-cert Secret "envoy-gateway" too. So the
# charm must publish a Service of exactly this name and serve that Secret's cert.
CONTROL_PLANE_NAME = "envoy-gateway"
XDS_PORT = 18000
WASM_PORT = 18002
# controller-runtime Prometheus /metrics endpoint exposed by the envoy-gateway binary.
METRICS_PORT = 19001

# Secrets minted by `envoy-gateway certgen`. They are app-scoped (not per-unit) and
# unmanaged by KRM, so they are deleted explicitly on last-unit teardown — otherwise a
# redeploy into the surviving namespace silently reuses the stale CA via idempotent
# certgen, masking a broken trust chain.
CERTGEN_SECRETS = ("envoy", "envoy-gateway", "envoy-rate-limit", "envoy-oidc-hmac")

# Sequential minor-version upgrades on upgrade-charm are not yet enforced; see
# https://github.com/canonical/service-mesh/issues/112

# Accepted values for the log-level config. Anything else falls back to the default
# rather than reaching the controller's config (an invalid value would crash-loop the
# controller with an opaque error).
DEFAULT_LOG_LEVEL = "info"
VALID_LOG_LEVELS = frozenset({"debug", "info", "warn", "error"})

# Docker/distribution tag grammar: a word char followed by up to 127 word/dot/dash
# chars, ASCII-only. Used to pull the version tag out of the controller's image
# reference. The controller binary self-reports no version, so the tag of the image the
# pod runs is the only source of truth for the deployed version. This is the tag grammar
# only, not the full reference grammar — enough to validate a candidate tag without
# pulling in a reference-parsing dependency.
_IMAGE_TAG = re.compile(r"[\w][\w.-]{0,127}", re.ASCII)


def _load_crd_yaml(directory: str) -> list:
    """Load all CRD YAML documents from crds/<directory>/*.yaml."""
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
            protocols=["grpc"],
            telemetries=["metrics"],
            rules=_rules,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self._metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": [f"*:{METRICS_PORT}"]}]}],
            alert_rules_path=str(SOURCE_PATH / "prometheus_alert_rules"),
            refresh_event=[self.on.envoy_gateway_pebble_ready],
        )
        self.ext_server = ExtensionServerRequirer(self)

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.update_status, self._reconcile)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.envoy_gateway_pebble_ready, self._reconcile)
        self.framework.observe(self.on["otlp"].relation_changed, self._reconcile)
        self.framework.observe(self.on["otlp"].relation_broken, self._reconcile)
        self.framework.observe(
            self.on["envoy-extension-server"].relation_changed, self._reconcile
        )
        self.framework.observe(
            self.on["envoy-extension-server"].relation_broken, self._reconcile
        )

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
    def _log_level(self) -> str:
        level = str(self.config["log-level"])
        if level not in VALID_LOG_LEVELS:
            logger.warning("Invalid log-level %r; falling back to %r", level, DEFAULT_LOG_LEVEL)
            return DEFAULT_LOG_LEVEL
        return level

    def _image_ref(self, resource: str) -> Optional[str]:
        """Return the OCI image reference for an oci-image resource, or None if absent."""
        try:
            path = self.model.resources.fetch(resource)
        except (ops.ModelError, NameError):
            return None
        data = yaml.safe_load(Path(path).read_text())
        return data.get("registrypath") if data else None

    @property
    def _workload_version(self) -> str:
        """Deployed controller version from its OCI image tag, or "" if untagged."""
        ref = self._image_ref("envoy-gateway-image")
        if not ref:
            return ""
        last = ref.split("@", 1)[0].rsplit("/", 1)[-1]
        _, sep, tag = last.partition(":")
        return tag if sep and _IMAGE_TAG.fullmatch(tag) else ""

    @property
    def _otlp_endpoint(self) -> Optional[str]:
        """Return the first OTLP endpoint URL from the relation, or None."""
        for ep in self.otlp.endpoints.values():
            return ep.endpoint
        return None

    def _otlp_metric_sink(self) -> Optional[MetricSink]:
        """Return an Envoy OpenTelemetry MetricSink for the OTLP endpoint, or None."""
        endpoint = self._otlp_endpoint
        if not endpoint:
            return None
        # EG's OpenTelemetry sink (control-plane and EnvoyProxy) exports over OTLP gRPC, so
        # the requirer asks for grpc and the port falls back to the OTLP/gRPC default (4317),
        # not the HTTP default (4318). The gRPC endpoint arrives as a bare host:port (no
        # scheme), so prefix "//" when needed for urlparse to read the host and port.
        parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
        if not parsed.hostname:
            return None
        return MetricSink(
            openTelemetry=OpenTelemetrySink(
                host=parsed.hostname,
                port=parsed.port or 4317,
            )
        )

    def _control_plane_secret(self) -> Optional[Secret]:
        """Return the certgen-issued control-plane TLS Secret, or None if absent."""
        # certgen names this Secret "envoy-gateway"; it holds the server cert the xDS server
        # presents and the CA proxies validate against. lightkube returns "data" already
        # base64-encoded (the Secret wire format).
        try:
            return self.lightkube_client.get(
                Secret, name=CONTROL_PLANE_NAME, namespace=self.model.name
            )
        except ApiError as e:
            if e.status.code == 404:
                return None
            raise

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

    def _reconcile(self, _event: ops.EventBase):
        """Reconcile the entire state of the charm.

        Steps:
          0. Publish observability — Grafana dashboards and OTLP alert rules are pure
             databag operations; publish them unconditionally so they are available
             even when other preconditions are not yet met.
          1. Check preconditions — trust and Pebble. Any unmet precondition halts
             reconciliation; status is set via _on_collect_status.
          2. Apply CRDs — Gateway API, Envoy Gateway, and GIE.
          3. Run certgen — mint the control-plane mTLS secrets; must precede the cert
             push, which serves the certgen-issued cert.
          4. Push config and certs — controller config YAML and the certgen control-plane
             cert into the gateway container.
          5. Reconcile control-plane Service — the "envoy-gateway" Service proxies and the
             API server dial for xDS.
          6. Reconcile EnvoyProxy — default resource with Juju-topology stats tags and OTLP sink.
          7. Reconcile GatewayClass — the shared "envoy" class ingress charms reference.
          8. Reconcile Pebble services — add the gateway layer and replan.

        Steps 3–8 defer cleanly on a k8s API 429 (freshly-established CRDs briefly return
        "storage is (re)initializing") — juju retries via the next event rather than
        flipping to error state during the sub-second window.
        """
        # Step 0: observability + identity + workload version — no cluster access needed
        self.unit.set_workload_version(self._workload_version)
        self.grafana_dashboards.update_dashboards()
        self.otlp.publish()
        # Advertise our control-plane identity so a related extension server can gate
        # itself to this GatewayClass/namespace. No-op (leader-gated) without a relation.
        self.ext_server.publish_controller_identity(
            controller_name=ENVOY_GATEWAY_CONTROLLER_NAME,
            namespace=self.model.name,
        )

        if not self._trusted:
            logger.warning("Charm is not trusted; skipping reconciliation")
            return
        if not self.unit.get_container(GATEWAY_CONTAINER).can_connect():
            logger.info("Pebble not ready; skipping reconciliation")
            return

        try:
            self._reconcile_crds()
        except _CrdsNotEstablishedError:
            logger.info("CRDs applied but not yet Established; deferring controller start")
            return

        # CRD Established=True marks the schema as registered but does not guarantee the
        # aggregated storage backend is serving reads yet — freshly-created CRDs briefly
        # return 429 "storage is (re)initializing" from list/get calls (a well-known k8s
        # race). Treat any 429 from the first-CR-list calls below as "come back on the
        # next event" rather than crashing the hook, so juju does not flip to error state
        # during the sub-second storage-init window; the next reconcile (pebble-ready,
        # update-status, or juju's own retry) will re-run and succeed.
        try:
            self._reconcile_certgen()
            self._reconcile_config_and_certs()
            self._reconcile_control_plane_service()
            self._reconcile_envoy_proxy()
            self._reconcile_gateway_class()
            self._reconcile_pebble_services()
        except ApiError as e:
            if e.status.code == 429:
                logger.info("k8s API returned 429 (%s); deferring", e.status.message)
                return
            raise

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Evaluate current state and add unit statuses."""
        if not self._trusted:
            event.add_status(
                ops.BlockedStatus(f"Trust not granted. Run 'juju trust {self.app.name}'")
            )
            return
        container = self.unit.get_container(GATEWAY_CONTAINER)
        if not container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble (envoy-gateway container)"))
            return
        if GATEWAY_CONTAINER not in container.get_plan().services:
            # Reconciliation has not yet started the controller — most commonly it is
            # still waiting for the CRDs to reach Established. Do not report Active.
            event.add_status(ops.MaintenanceStatus("Setting up Envoy Gateway control plane"))
            return
        if not self._container_healthy(container):
            event.add_status(
                ops.WaitingStatus("Waiting for envoy-gateway controller to become healthy")
            )
            return
        if self._foreign_gateway_class_owner() is not None:
            event.add_status(
                ops.BlockedStatus(f"Existing '{GATEWAY_CLASS_NAME}' GatewayClass; see logs")
            )
            return
        event.add_status(ops.ActiveStatus())

    def _on_remove(self, _event: ops.RemoveEvent):
        """Remove app-scoped resources on app removal. CRDs are left in place."""
        # The xDS Service, default EnvoyProxy, shared GatewayClass and certgen Secrets are
        # app-scoped (the GatewayClass is cluster-scoped but singly owned by this app), so
        # remove them only when the whole application is going away (planned_units == 0),
        # not on a scale-down where peer units still rely on them.
        if self.app.planned_units() != 0:
            logger.info("Unit removed but application remains; leaving resources in place")
            return
        # KRM swallows the expected 404 via ignore_missing; any other API error surfaces.
        self._control_plane_service_krm().delete(ignore_missing=True)
        self._envoy_proxy_krm().delete(ignore_missing=True)
        self._gateway_class_krm().delete(ignore_missing=True)
        self._delete_certgen_secrets()

    def _delete_certgen_secrets(self):
        """Delete the certgen-minted Secrets so a redeploy re-mints under a fresh CA."""
        for name in CERTGEN_SECRETS:
            try:
                self.lightkube_client.delete(Secret, name=name, namespace=self.model.name)
            except ApiError as e:
                if e.status.code != 404:
                    raise

    def _reconcile_crds(self):
        """Apply Gateway API + Envoy Gateway + GIE CRDs."""
        for scope, directory in CRD_SCOPES.items():
            self._crd_krm(scope).reconcile(_load_crd_yaml(directory))

        # Wait for all CRDs to reach Established=True before returning so the controller
        # does not start against unregistered schemas.
        if not self._crds_established():
            raise _CrdsNotEstablishedError()

    def _reconcile_config_and_certs(self):
        """Push controller config and the certgen control-plane cert into the container."""
        # The config push is unconditional: the controller starts with
        # --config-path /etc/envoy-gateway/config.yaml, so the file must exist before replan,
        # and it does not depend on the cert Secret.
        self._push_files(
            GATEWAY_CONTAINER,
            {"/etc/envoy-gateway/config.yaml": self._construct_envoy_gateway_config()},
        )

        # Envoy Gateway reads its xDS-server TLS from /certs/{tls.crt,tls.key,ca.crt}. The
        # cert MUST be the certgen "envoy-gateway" Secret: Envoy Proxy pods are wired by EG to
        # trust the certgen CA, so a cert from any other CA fails the proxy<->control-plane
        # mTLS handshake. certgen runs first, so the Secret exists by now; if it somehow does
        # not, push config but skip the certs rather than serving a wrong cert.
        secret = self._control_plane_secret()
        if not secret or not secret.data:
            logger.info("Control-plane cert Secret not present yet; skipping cert push")
            return
        cert_pem = base64.b64decode(secret.data["tls.crt"]).decode()
        key_pem = base64.b64decode(secret.data["tls.key"]).decode()
        ca_pem = base64.b64decode(secret.data["ca.crt"]).decode()

        container = self.unit.get_container(GATEWAY_CONTAINER)
        if not container.can_connect():
            return
        container.push("/certs/tls.crt", cert_pem, make_dirs=True)
        # The private key is restricted to owner read/write; the cert and CA are public.
        container.push("/certs/tls.key", key_pem, make_dirs=True, permissions=0o600)
        container.push("/certs/ca.crt", ca_pem, make_dirs=True)

    def _reconcile_control_plane_service(self):
        """Publish the Service clients use to reach the control plane."""
        # Envoy Gateway hardcodes the proxy bootstrap to dial envoy-gateway.<ns>.svc on the
        # xDS (18000) and wasm (18002) ports — names its own Helm chart supplies. The charm
        # app Service is named after the app, so without this Service the proxy DNS lookup
        # yields no endpoints ("no healthy upstream") and Gateways never reach Programmed=True.
        self._control_plane_service_krm().reconcile([self._construct_control_plane_service()])

    def _construct_control_plane_service(self) -> Service:
        """Construct the ``envoy-gateway`` Service selecting the controller pods."""
        ports = [
            ServicePort(name="xds", port=XDS_PORT, targetPort=XDS_PORT),
            ServicePort(name="wasm", port=WASM_PORT, targetPort=WASM_PORT),
        ]
        return Service(
            metadata=ObjectMeta(name=CONTROL_PLANE_NAME, namespace=self.model.name),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": self.app.name},
                ports=ports,
            ),
        )

    def _reconcile_envoy_proxy(self):
        """Manage the default EnvoyProxy resource (stats tags + OTLP sink)."""
        self._envoy_proxy_krm().reconcile([self._construct_envoy_proxy()])

    def _reconcile_gateway_class(self):
        """Manage the shared "envoy" GatewayClass that ingress charms reference."""
        # Skip (do not overwrite) a foreign "envoy" class; _on_collect_status blocks instead.
        foreign_owner = self._foreign_gateway_class_owner()
        if foreign_owner is not None:
            logger.warning(
                "GatewayClass %r already exists (owned by %s); refusing to manage it. The "
                "envoy charms are designed for a single cluster-wide envoy-controller that "
                "owns the one %r GatewayClass; remove the other controller/install or this "
                "one to resolve.",
                GATEWAY_CLASS_NAME,
                foreign_owner,
                GATEWAY_CLASS_NAME,
            )
            return
        self._gateway_class_krm().reconcile([self._construct_gateway_class()])

    def _foreign_gateway_class_owner(self) -> Optional[str]:
        """Return the owner of a pre-existing "envoy" GatewayClass we do not manage."""
        # None if the class is absent or carries this app's KRM instance label; otherwise the
        # foreign owner label ("<unmanaged>" if it has none), so the cluster-wide singleton is
        # never fought over by a second controller or a non-Juju install.
        try:
            existing = self.lightkube_client.get(GatewayClass, name=GATEWAY_CLASS_NAME)
        except ApiError as e:
            if e.status.code == 404:
                return None
            raise
        labels = (existing.metadata.labels if existing.metadata else None) or {}
        owner = labels.get(GATEWAY_CLASS_OWNER_LABEL)
        mine = create_charm_default_labels(
            self.app.name, self.model.name, scope=GATEWAY_CLASS_SCOPE
        )[GATEWAY_CLASS_OWNER_LABEL]
        if owner == mine:
            return None
        return owner or "<unmanaged>"

    def _reconcile_certgen(self):
        """Provision the control-plane secrets Envoy Gateway requires via its certgen."""
        # Upstream ships a one-shot certgen Job that mints the control-plane mTLS secrets
        # (envoy, envoy-gateway, envoy-rate-limit) and the envoy-oidc-hmac secret the OAuth2
        # filter signs OIDC state/session cookies with. Without these the controller blocks on
        # a missing "envoy" secret and never serves xDS.
        #
        # Skip once *all* Secrets exist so certgen is not re-run on every event (including the
        # 5-minute update-status), where a transient exec failure would tip the charm into
        # error state. The guard requires every Secret (not just envoy-gateway): if certgen is
        # interrupted after creating some but not the load-bearing "envoy" Secret, or one is
        # deleted out-of-band, keying on a single Secret would skip certgen forever and leave
        # the controller permanently blocked with no recovery path.
        if self._certgen_complete():
            return
        # We have no Job, so run certgen in-place in the gateway container. It is idempotent —
        # existing secrets are left untouched (no --overwrite) so values stay stable across
        # reconciles and scaled units. --disable-topology-injector stops certgen from patching
        # an unrelated injector webhook. ENVOY_GATEWAY_NAMESPACE must be set or certgen targets
        # the non-existent default "envoy-gateway-system" namespace.
        container = self.unit.get_container(GATEWAY_CONTAINER)
        try:
            container.exec(
                ["envoy-gateway", "certgen", "--disable-topology-injector"],
                environment={"ENVOY_GATEWAY_NAMESPACE": self.model.name},
            ).wait()
        except ExecError as e:
            logger.error(
                "certgen failed (exit %s): stdout=%s stderr=%s",
                e.exit_code,
                e.stdout,
                e.stderr,
            )
            raise

    def _certgen_complete(self) -> bool:
        """Return True when every certgen-minted control-plane Secret exists."""
        for name in CERTGEN_SECRETS:
            try:
                self.lightkube_client.get(Secret, name=name, namespace=self.model.name)
            except ApiError as e:
                if e.status.code == 404:
                    return False
                raise
        return True

    def _reconcile_pebble_services(self):
        """Add the gateway Pebble layer and replan."""
        gateway = self.unit.get_container(GATEWAY_CONTAINER)
        gateway.add_layer("envoy-gateway", self._construct_gateway_layer(), combine=True)
        gateway.replan()

    def _construct_envoy_gateway_config(self) -> str:
        """Construct the Envoy Gateway controller config YAML."""
        # extensionApis (Backend + EnvoyPatchPolicy) is left enabled unconditionally; see
        # https://github.com/canonical/service-mesh/issues/110 for the rationale and tradeoff.
        envoy_gateway: dict[str, Any] = {
            "logging": {"level": {"default": self._log_level}},
            "extensionApis": {
                "enableEnvoyPatchPolicy": True,
                "enableBackend": True,
            },
        }
        sink = self._otlp_metric_sink()
        if sink:
            telemetry = TelemetryConfig(metrics=MetricsConfig(sinks=[sink]))
            envoy_gateway["telemetry"] = telemetry.model_dump(by_alias=True, exclude_none=True)
        # When an extension server is related, wire its gRPC endpoint into extensionManager so
        # EG delegates xDS fine-tuning to it. Omitted when unrelated (or the provider has not
        # published yet) so the controller never dials a non-existent endpoint.
        extension = self.ext_server.get_extension_server_data()
        if extension and extension.extension_server_fqdn and extension.extension_server_port:
            envoy_gateway["extensionManager"] = self._extension_manager(
                extension.extension_server_fqdn, int(extension.extension_server_port)
            )
        return yaml.safe_dump(
            {
                "apiVersion": "gateway.envoyproxy.io/v1alpha1",
                "kind": "EnvoyGateway",
                **envoy_gateway,
            }
        )

    @staticmethod
    def _extension_manager(fqdn: str, port: int) -> dict[str, Any]:
        """Build the extensionManager block pointing at an extension server."""
        # The xdsTranslator hooks mirror what the extension server needs to fine-tune the
        # translated xDS: all listener/route/cluster/secret resources are passed through, and
        # it runs post the Translation/Cluster/Route stages (Envoy AI Gateway's required hook
        # set; see the upstream envoy-gateway-values.yaml).
        # backendResources whitelists InferencePool as an allowed HTTPRoute backendRef so EG
        # delegates it to the extension server for xDS translation (mirrors the upstream
        # inference-pool addon values; fix for
        # https://github.com/canonical/service-mesh/issues/128). Today the only extension
        # server is Envoy AI Gateway, which handles InferencePool, so this is always safe when
        # the relation is up; a second extension-server type would need an id on the interface
        # so this can be enabled per-provider instead of unconditionally.
        return {
            "hooks": {
                "xdsTranslator": {
                    "translation": {
                        "listener": {"includeAll": True},
                        "route": {"includeAll": True},
                        "cluster": {"includeAll": True},
                        "secret": {"includeAll": True},
                    },
                    "post": ["Translation", "Cluster", "Route"],
                }
            },
            "backendResources": [
                {
                    "group": "inference.networking.k8s.io",
                    "kind": "InferencePool",
                    "version": "v1",
                },
            ],
            "service": {"fqdn": {"hostname": fqdn, "port": port}},
        }

    def _construct_envoy_proxy(self) -> EnvoyProxy:
        """Construct the default EnvoyProxy resource (identity stats tags + OTLP sink).

        All identity travels through `stats_config.stats_tags`, so every metric
        carries it as plain labels end-to-end (no collector-side configuration):
          - Juju topology (fixed per app) — literal values.
          - Owning Gateway (per pod) — `$(ENVOY_GATEWAY_{NAME,NAMESPACE})` values.
            Envoy never substitutes anything in `fixed_value`, but it never sees
            the refs: envoy-gateway hands the bootstrap to Envoy as a
            `--config-yaml` container *argument*, and the kubelet expands `$(VAR)`
            in args against the container's env at pod start (the same mechanism
            envoy-gateway uses for `$(ENVOY_SERVICE_ZONE)`). The downward API
            (below) materialises the owning-Gateway pod labels as exactly those
            env vars.
        Without the per-Gateway tags, N Gateways under one EnvoyProxy produce
        identical series signatures and Prometheus dedup silently collapses them
        into one indistinguishable stream. Pod-level identity is intentionally
        omitted — cardinality would scale with replicas without answering a
        question we can't already answer per-Gateway. OTLP *resource* attributes
        are deliberately not used: the COS otelcol charm's prometheusremotewrite
        exporter drops them (no resource_to_telemetry_conversion), so identity
        shipped that way never reaches Prometheus as labels.
        """
        fixed_tags: list[dict[str, str]] = [
            {"tag_name": "juju_model", "fixed_value": self.model.name},
            {"tag_name": "juju_model_uuid", "fixed_value": self.model.uuid},
            {"tag_name": "juju_application", "fixed_value": self.app.name},
            {"tag_name": "juju_charm", "fixed_value": self.meta.name},
            {"tag_name": "gateway_name", "fixed_value": "$(ENVOY_GATEWAY_NAME)"},
            {
                "tag_name": "gateway_namespace",
                "fixed_value": "$(ENVOY_GATEWAY_NAMESPACE)",
            },
        ]
        json_patches: list[JSONPatchOperation] = [
            JSONPatchOperation(
                op="add",
                path="/stats_config/stats_tags/-",
                value=tag,
            )
            for tag in fixed_tags
        ]
        sink = self._otlp_metric_sink()
        telemetry = TelemetryConfig(metrics=MetricsConfig(sinks=[sink])) if sink else None
        spec = EnvoyProxySpec(
            bootstrap=ProxyBootstrap(type="JSONPatch", jsonPatches=json_patches),
            telemetry=telemetry,
        )
        spec_dict = spec.model_dump(by_alias=True, exclude_none=True)
        env = [
            {
                "name": "ENVOY_GATEWAY_NAME",
                "valueFrom": {
                    "fieldRef": {
                        "fieldPath": (
                            "metadata.labels"
                            "['gateway.envoyproxy.io/owning-gateway-name']"
                        )
                    }
                },
            },
            {
                "name": "ENVOY_GATEWAY_NAMESPACE",
                "valueFrom": {
                    "fieldRef": {
                        "fieldPath": (
                            "metadata.labels"
                            "['gateway.envoyproxy.io/owning-gateway-namespace']"
                        )
                    }
                },
            },
        ]
        # `provider` is not on canonical_service_mesh.EnvoyProxySpec yet, so merge
        # onto the dumped dict verbatim.
        spec_dict["provider"] = {
            "type": "Kubernetes",
            "kubernetes": {
                "envoyDeployment": {
                    "container": {"env": env},
                }
            },
        }
        return EnvoyProxy(
            metadata=ObjectMeta(name=self.app.name, namespace=self.model.name),
            spec=spec_dict,
        )

    def _construct_gateway_class(self) -> GatewayClass:
        """Construct the shared "envoy" GatewayClass."""
        # parametersRef binds every Gateway of this class to the default EnvoyProxy (the
        # cross-namespace attachment point) so proxies across all ingress models inherit its
        # OTLP sink and Juju-topology stats tags.
        spec = GatewayClassSpec(
            controllerName=ENVOY_GATEWAY_CONTROLLER_NAME,
            parametersRef=ParametersRef(
                group=ENVOY_PROXY_GROUP,
                kind=ENVOY_PROXY_KIND,
                name=self.app.name,
                namespace=self.model.name,
            ),
        )
        return GatewayClass(
            metadata=ObjectMeta(name=GATEWAY_CLASS_NAME),
            spec=spec.model_dump(by_alias=True, exclude_none=True),
        )

    def _crds_established(self) -> bool:
        """Return True when every bundled CRD is present AND has Established=True."""
        # Each expected CRD (from the bundled YAML) must be found in the deployed set and carry
        # Established=True. Checking presence — not just iterating whatever the list returns —
        # guards against an empty/lagging label-indexed list being mistaken for "all
        # established", which would green-light the controller against unregistered schemas.
        for scope, directory in CRD_SCOPES.items():
            expected = {crd.metadata.name for crd in _load_crd_yaml(directory)}
            try:
                deployed = {
                    crd.metadata.name: crd
                    for crd in self._crd_krm(scope).get_deployed_resources()
                }
            except ApiError:
                return False
            for name in expected:
                crd = deployed.get(name)
                if crd is None:
                    logger.debug("CRD %s not yet present", name)
                    return False
                conditions = (crd.status.conditions or []) if crd.status else []
                if not any(
                    c.type == "Established" and c.status == "True" for c in conditions
                ):
                    logger.debug("CRD %s not yet Established", name)
                    return False
        return True

    def _construct_gateway_layer(self) -> Layer:
        """Construct the Pebble layer for the Envoy Gateway controller."""
        # Envoy Gateway does not hot-reload config.yaml, and replan only restarts a service
        # when its *layer* changes — not when a pushed file does. Stamp a hash of the rendered
        # config into the service environment so a config change (log-level, OTLP sink) alters
        # the layer and replan restarts the controller to pick it up.
        config_hash = hashlib.sha256(
            self._construct_envoy_gateway_config().encode()
        ).hexdigest()
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
                        "environment": {
                            "ENVOY_GATEWAY_NAMESPACE": self.model.name,
                            "EG_CONFIG_HASH": config_hash,
                        },
                        "on-check-failure": {"liveness": "restart"},
                    }
                },
                "checks": {
                    # Only liveness is wired to restart; a sustained readiness failure
                    # leaves the unit in "waiting" (controller alive but not serving)
                    # rather than restart-looping. period/threshold are tuned so a slow
                    # :8081 probe bind on a loaded cluster does not trip a false restart.
                    "liveness": {
                        "override": "replace",
                        "level": "alive",
                        "period": "10s",
                        "timeout": "3s",
                        "threshold": 3,
                        "http": {"url": "http://localhost:8081/healthz"},
                    },
                    "readiness": {
                        "override": "replace",
                        "level": "ready",
                        "period": "10s",
                        "timeout": "3s",
                        "threshold": 3,
                        "http": {"url": "http://localhost:8081/readyz"},
                    },
                },
            }
        )

    def _push_files(self, container_name: str, files: dict[str, str]):
        """Push a map of path -> content into a container."""
        container = self.unit.get_container(container_name)
        if not container.can_connect():
            return
        for path, content in files.items():
            container.push(path, content, make_dirs=True)

    @staticmethod
    def _container_healthy(container: ops.Container) -> bool:
        """Return True if the container has no failing ready-level checks."""
        # Callers must ensure the service is in the plan first (see _on_collect_status); a
        # service that has not been started yet is "not healthy", not "healthy".
        try:
            checks = container.get_checks(level=ops.pebble.CheckLevel.READY)
        except ops.pebble.Error:
            return False
        return all(c.status == ops.pebble.CheckStatus.UP for c in checks.values())

    def _crd_krm(self, scope: str) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(self.app.name, self.model.name, scope=scope),
            resource_types={CustomResourceDefinition},
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

    def _gateway_class_krm(self) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=GATEWAY_CLASS_SCOPE
            ),
            resource_types={GatewayClass},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )


if __name__ == "__main__":
    ops.main(EnvoyControllerCharm)
