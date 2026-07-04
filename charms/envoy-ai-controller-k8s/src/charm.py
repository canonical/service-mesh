#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Envoy AI Gateway control plane."""

# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false
# Lightkube generic resource types (create_namespaced_resource) lack proper type stubs.

import base64
import logging
import re
from pathlib import Path
from typing import Optional

import ops
import yaml
from canonical_service_mesh.interfaces.envoy_extension_server import ExtensionServerProvider
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    create_charm_default_labels,
)
from charmlibs.interfaces.tls_certificates import (
    CertificateRequestAttributes,
    TLSCertificatesRequiresV4,
)
from lightkube import ApiError, Client
from lightkube.codecs import load_all_yaml
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
CRDS_PATH = SOURCE_PATH / "crds"

AI_CRD_SCOPE = "ai-gateway-crds"
WEBHOOK_SCOPE = "extproc-webhook"

# CRD reconcile scope -> the crds/<dir> the bundle is loaded from.
CRD_SCOPES = {AI_CRD_SCOPE: "ai-gateway"}

CONTAINER = "ai-gateway"

# Extension Server gRPC endpoint (Envoy Gateway's Extension Server default). Also serves
# the gRPC health service, so the Pebble check probes this port over TCP.
EXTENSION_SERVER_PORT = 1063
# ExtProc sidecar-injector admission webhook. The API server dials the app Service
# over TLS on this port.
WEBHOOK_PORT = 9443
# controller-runtime manager metrics.
METRICS_PORT = 8080

# The controller reads its serving cert from <CERT_DIR>/<TLS_CERT_NAME|TLS_KEY_NAME>,
# and the CA bundle it patches onto the webhook from <CERT_DIR>/<CA_BUNDLE_NAME>.
CERT_DIR = "/certs"
TLS_CERT_NAME = "tls.crt"
TLS_KEY_NAME = "tls.key"
CA_BUNDLE_NAME = "ca.crt"

# The controller patches the caBundle of a pre-existing MutatingWebhookConfiguration
# named "<WEBHOOK_CONFIG_NAME>.<POD_NAMESPACE>" at startup (Helm creates it upstream);
# the prefix is hardcoded in the controller and must match exactly or it exits.
WEBHOOK_CONFIG_NAME = "envoy-ai-gateway-gateway-pod-mutator"

COMMAND = "/app"

# Accepted values for the log-level config. Anything else falls back to the default
# rather than reaching the controller's -logLevel flag (an invalid value would fail to
# start with an opaque error).
DEFAULT_LOG_LEVEL = "info"
VALID_LOG_LEVELS = frozenset({"debug", "info", "warn", "error"})

# Docker/distribution tag grammar: a word char followed by up to 127 word/dot/dash
# chars, ASCII-only. Used to pull the version tag out of the controller's image
# reference. The controller binary self-reports no version (its image sets no OCI
# version label and cmd/controller wires in no version flag or endpoint), so the tag
# of the image the pod runs is the only source of truth for the deployed version.
# This is the tag grammar only, not the full reference grammar — enough to validate a
# candidate tag without pulling in a reference-parsing dependency.
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


class EnvoyAiControllerCharm(ops.CharmBase):
    """Charm for managing the Envoy AI Gateway control plane."""

    def __init__(self, *args):
        super().__init__(*args)
        self._lightkube_field_manager = self.app.name
        self._lightkube_client: Optional[Client] = None

        self.ext_server = ExtensionServerProvider(self)
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
        self.framework.observe(self.on.ai_gateway_pebble_ready, self._reconcile)
        self.framework.observe(self.tls.on.certificate_available, self._reconcile)
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
        ref = self._image_ref("ai-gateway-image")
        if not ref:
            return ""
        last = ref.split("@", 1)[0].rsplit("/", 1)[-1]
        _, sep, tag = last.partition(":")
        return tag if sep and _IMAGE_TAG.fullmatch(tag) else ""

    @property
    def _service_fqdn(self) -> str:
        """Cluster-internal FQDN of the app Service Juju manages for this charm."""
        # The extension-server gRPC endpoint and the ExtProc webhook are both reached
        # through Juju's application Service (its ports are opened via set_ports); no
        # charm-managed Service is needed.
        return f"{self.app.name}.{self.model.name}.svc.cluster.local"

    @property
    def _certificate_request(self) -> CertificateRequestAttributes:
        """Cert request covering the names the API server may dial the webhook by."""
        app, model = self.app.name, self.model.name
        # No CN: the spec requires the CN to match one of the SANs, and the service FQDN
        # can exceed the 64-char X.509 CN limit under long model names. Every dial-able
        # name goes in the SANs, which is where the API server validates the cert anyway.
        return CertificateRequestAttributes(
            sans_dns=frozenset(
                {
                    app,
                    f"{app}.{model}",
                    f"{app}.{model}.svc",
                    self._service_fqdn,
                }
            ),
        )

    @property
    def _tls_ready(self) -> bool:
        """Return True when the certificates relation has issued a cert and key."""
        if not self.model.get_relation("certificates"):
            return False
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

    def _reconcile(self, _event: ops.EventBase):
        """Reconcile the entire state of the charm.

        Steps:
          1. Check preconditions — trust and Pebble. Any unmet precondition halts
             reconciliation; status is set via _on_collect_status.
          2. Apply CRDs — the aigateway.envoyproxy.io schemas the controller indexes
             at startup. Halts until they reach Established.
          3. Push the webhook serving cert into the container. Halts until issued.
          4. Open the controller's ports on Juju's application Service (gRPC + webhook
             + metrics); no charm-managed Service is needed.
          5. Reconcile the ExtProc MutatingWebhookConfiguration (caBundle = issuing CA).
          6. Publish the Extension Server address over the relation (the AI on/off switch).
          7. Reconcile Pebble services — add the controller layer and replan.
        """
        self.unit.set_workload_version(self._workload_version)

        # Step 1: preconditions
        if not self._trusted:
            logger.warning("Charm is not trusted; skipping reconciliation")
            return
        if not self.unit.get_container(CONTAINER).can_connect():
            logger.info("Pebble not ready; skipping reconciliation")
            return

        # Step 2: CRDs — raises _CrdsNotEstablishedError if API server not ready yet
        try:
            self._reconcile_crds()
        except _CrdsNotEstablishedError:
            logger.info("CRDs applied but not yet Established; deferring controller start")
            return

        # Step 3: webhook serving cert
        cert = self._webhook_cert()
        if cert is None:
            logger.info("TLS certificate not issued yet; skipping cert-dependent reconcile")
            return
        ca_pem, cert_pem, key_pem = cert
        self._push_files(
            CONTAINER,
            {
                f"{CERT_DIR}/{TLS_CERT_NAME}": cert_pem,
                f"{CERT_DIR}/{TLS_KEY_NAME}": key_pem,
                # The controller reads this to patch the webhook's caBundle; it exits
                # if the file is missing. Same CA we set on the webhook below, so its
                # equality check passes and it does not fight our field manager.
                f"{CERT_DIR}/{CA_BUNDLE_NAME}": ca_pem,
            },
        )

        # Without an active envoy-extension-server relation, tear down the ExtProc webhook.
        # Leaving it in place would keep intercepting Envoy Gateway data-plane pod CREATEs
        # against a Service the API server can no longer usefully reach — either injecting
        # against a stale controller or, under failurePolicy=Fail, blocking pod creation.
        # `.active` catches the relation-broken hook, where get_relation() still returns
        # the departing relation object.
        relation = self.model.get_relation("envoy-extension-server")
        if not relation or not relation.active:
            logger.info("envoy-extension-server relation absent; removing ExtProc webhook")
            self._webhook_krm().reconcile([])
            return

        # Step 4: expose the controller's ports on Juju's application Service
        self.unit.set_ports(EXTENSION_SERVER_PORT, WEBHOOK_PORT, METRICS_PORT)
        # Step 5: ExtProc admission webhook (issuing CA as caBundle)
        self._webhook_krm().reconcile([self._construct_webhook(ca_pem)])
        # Step 6: advertise the Extension Server endpoint (AI on/off switch)
        self.ext_server.publish_data(
            extension_server_fqdn=self._service_fqdn,
            extension_server_port=str(EXTENSION_SERVER_PORT),
        )
        # Step 7: Pebble services
        self._reconcile_pebble_services()

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Evaluate current state and add unit statuses."""
        # Each check returns after adding its status so the check order encodes priority.
        # ops would otherwise pick by its own ladder (Maintenance > Waiting), which would
        # mask specific reasons like "Waiting for TLS certificate" behind "Setting up".
        # The returns also guard: get_plan()/get_checks() below raise without a connection.
        if not self._trusted:
            event.add_status(
                ops.BlockedStatus(f"Trust not granted. Run 'juju trust {self.app.name}'")
            )
            return
        container = self.unit.get_container(CONTAINER)
        if not container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble (ai-gateway container)"))
            return
        if not self.model.get_relation("certificates"):
            event.add_status(ops.BlockedStatus("Missing relation: certificates"))
            return
        if not self._tls_ready:
            event.add_status(ops.WaitingStatus("Waiting for TLS certificate"))
            return
        if not self.model.get_relation("envoy-extension-server"):
            event.add_status(
                ops.BlockedStatus("Missing relation: envoy-extension-server")
            )
            return
        if CONTAINER not in container.get_plan().services:
            # Reconciliation has not yet started the controller — most commonly it is
            # still waiting for the CRDs to reach Established. Do not report Active.
            event.add_status(
                ops.MaintenanceStatus("Setting up Envoy AI Gateway control plane")
            )
            return
        if not self._container_healthy(container):
            event.add_status(
                ops.WaitingStatus("Waiting for AI Gateway controller to become healthy")
            )
            return
        event.add_status(ops.ActiveStatus())

    def _on_remove(self, _event: ops.RemoveEvent):
        """Remove the ExtProc webhook on app removal; CRDs are left in place."""
        # The MutatingWebhookConfiguration is cluster-scoped and app-owned, so it must only
        # be removed when the whole application is going away (planned_units == 0), not on a
        # scale-down where peer units still rely on it. The application Service is managed by
        # Juju, so it is not touched here. KRM swallows the expected 404 via ignore_missing;
        # any other API error is allowed to surface.
        if self.app.planned_units() != 0:
            logger.info("Unit removed but application remains; leaving resources in place")
            return
        self._webhook_krm().delete(ignore_missing=True)
        # CRDs are intentionally NOT deleted here (per spec). They are cluster-scoped and
        # may be shared with other Envoy AI Gateway installs; deleting them would cascade
        # to every AI Gateway custom resource in the cluster, including ones this app does
        # not own. Leave them for an operator to remove deliberately.

    def _reconcile_crds(self):
        """Apply the aigateway.envoyproxy.io CRDs and wait for Established."""
        # The controller indexes the v1beta1 schemas at startup and exits if they are
        # not registered, so the controller is not started until every CRD is Established.
        for scope, directory in CRD_SCOPES.items():
            self._crd_krm(scope).reconcile(_load_crd_yaml(directory))

        if not self._crds_established():
            raise _CrdsNotEstablishedError()

    def _crds_established(self) -> bool:
        """Return True when every bundled CRD is present AND has Established=True."""
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

    def _reconcile_pebble_services(self):
        """Add the controller Pebble layer and replan."""
        container = self.unit.get_container(CONTAINER)
        container.add_layer(CONTAINER, self._construct_pebble_layer(), combine=True)
        container.replan()

    def _webhook_cert(self) -> Optional[tuple[str, str, str]]:
        """Return the issued (ca, cert, key) PEMs, or None if not yet available."""
        if not self._tls_ready:
            return None
        certs, key = self.tls.get_assigned_certificates()
        return str(certs[0].ca), str(certs[0].certificate), str(key)

    def _construct_webhook(self, ca_pem: str) -> MutatingWebhookConfiguration:
        """Construct the ExtProc sidecar-injector MutatingWebhookConfiguration."""
        webhook = MutatingWebhook(
            name=self._service_fqdn,
            admissionReviewVersions=["v1"],
            sideEffects="None",
            failurePolicy="Fail",
            timeoutSeconds=10,
            # Scope the webhook to Envoy Gateway data-plane pods only. Without this it
            # intercepts every pod CREATE in the namespace — including the controller's
            # own pod — so a controller restart deadlocks (the API server can't create
            # the pod because the down controller can't serve the webhook that gates it).
            objectSelector=LabelSelector(
                matchLabels={"app.kubernetes.io/managed-by": "envoy-gateway"}
            ),
            clientConfig=WebhookClientConfig(
                # The API server dials the webhook Service over TLS, validating the served
                # cert against caBundle, so caBundle must be the CA that issued the serving
                # cert. caBundle is a k8s []byte field, so the PEM is base64-encoded on wire.
                caBundle=base64.b64encode(ca_pem.encode()).decode(),
                service=ServiceReference(
                    name=self.app.name,
                    namespace=self.model.name,
                    path="/mutate",
                    port=WEBHOOK_PORT,
                ),
            ),
            rules=[
                RuleWithOperations(
                    apiGroups=[""],
                    apiVersions=["v1"],
                    operations=["CREATE"],
                    resources=["pods"],
                    scope="Namespaced",
                )
            ],
        )
        return MutatingWebhookConfiguration(
            metadata=ObjectMeta(name=f"{WEBHOOK_CONFIG_NAME}.{self.model.name}"),
            webhooks=[webhook],
        )

    def _construct_pebble_layer(self) -> Layer:
        """Construct the Pebble layer for the AI Gateway controller."""
        # The controller's gRPC health service listens on the Extension Server port, so
        # Pebble probes that port over TCP (Pebble has no gRPC check). Only liveness is
        # wired to restart; a sustained readiness failure leaves the unit "waiting"
        # (controller alive but not serving) rather than restart-looping.
        args = [
            COMMAND,
            f"-logLevel={self._log_level}",
            f"--tlsCertDir={CERT_DIR}",
            f"--tlsCertName={TLS_CERT_NAME}",
            f"--tlsKeyName={TLS_KEY_NAME}",
            f"--webhookPort={WEBHOOK_PORT}",
            "--enableLeaderElection=true",
            "--rootPrefix=/",
        ]
        # The controller stamps this ExtProc sidecar image into Envoy Gateway data-plane
        # pods. Sourced from the swappable oci-image resource so operators can pin it;
        # omitted when unset so the controller falls back to its built-in default rather
        # than receiving an empty value.
        extproc_image = self._image_ref("ai-extproc-image")
        if extproc_image:
            args.append(f"--extProcImage={extproc_image}")
        return Layer(
            {
                "summary": "Envoy AI Gateway",
                "description": "Envoy AI Gateway controller",
                "services": {
                    CONTAINER: {
                        "override": "replace",
                        "summary": "Envoy AI Gateway controller",
                        "command": " ".join(args),
                        "startup": "enabled",
                        "environment": {"POD_NAMESPACE": self.model.name},
                        "on-check-failure": {"liveness": "restart"},
                    }
                },
                "checks": {
                    "liveness": {
                        "override": "replace",
                        "level": "alive",
                        "period": "10s",
                        "timeout": "3s",
                        "threshold": 3,
                        "tcp": {"port": EXTENSION_SERVER_PORT},
                    },
                    "readiness": {
                        "override": "replace",
                        "level": "ready",
                        "period": "10s",
                        "timeout": "3s",
                        "threshold": 3,
                        "tcp": {"port": EXTENSION_SERVER_PORT},
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
        # Callers must ensure the service is in the plan first (see _on_collect_status);
        # a service that has not been started yet is "not healthy", not "healthy".
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

    def _webhook_krm(self) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=WEBHOOK_SCOPE
            ),
            resource_types={MutatingWebhookConfiguration},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )


if __name__ == "__main__":
    ops.main(EnvoyAiControllerCharm)
