#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for exposing Kubernetes workloads onto a tailnet.

This charm lives in a user application's model and provides the app an entrypoint
to the tailnet via the `ingress` relation. For each related application it declares
a LoadBalancer Service with `loadBalancerClass: tailscale` via lightkube. It has no
workload container: a cluster-wide Tailscale operator (deployed by tailscale-k8s)
reconciles that Service onto the tailnet, then writes the resulting tailnet hostname
back onto the Service status, which this charm reads and publishes to the requirer.
"""

# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
# Lightkube status sub-objects are loosely typed (dicts / optional models).

import dataclasses
import logging
import time
from typing import List, Optional, Tuple

import ops
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    create_charm_default_labels,
)
from canonical_service_mesh.k8s.types import LightkubeResourcesList
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider, IngressRequirerData
from lightkube import ApiError, Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from lightkube.resources.rbac_authorization_v1 import ClusterRole

logger = logging.getLogger(__name__)

# The LoadBalancerClass the cluster-wide Tailscale operator watches for. Creating a
# Service with this class is the entire (relationless) contract with the operator.
TAILSCALE_LOAD_BALANCER_CLASS = "tailscale"

# Annotation the operator reads to name the device it registers on the tailnet.
TAILSCALE_HOSTNAME_ANNOTATION = "tailscale.com/hostname"

# Condition the operator writes onto the Service to report proxy progress. The
# operator names it "TailscaleProxyReady" (verified against the upstream operator
# source, cmd/k8s-operator/svc.go); the shorter "ProxyReady" in the spec is the
# Go constant name, not the on-wire condition type.
PROXY_READY_CONDITION = "TailscaleProxyReady"
# Terminal (non-recoverable) reasons on that condition; these fail the reconcile.
PROXY_ERROR_REASONS = frozenset({"ProxyInvalid", "ProxyFailed"})

SERVICE_SCOPE = "tailscale-service"

# How often to re-check the Service status while waiting for the tailnet address.
_POLL_INTERVAL_SECONDS = 5


@dataclasses.dataclass(frozen=True)
class _ProxyState:
    """The beacon's view of one exposed app, derived from its Service status.

    Attributes:
        hostname: The tailnet (MagicDNS) hostname once the proxy is ready, else None.
        pending: True when the proxy is still coming up (no terminal error, no address).
        error: True when the operator reports a terminal ProxyInvalid/ProxyFailed.
        message: The operator's human-readable message for the current condition.
    """

    hostname: Optional[str]
    pending: bool
    error: bool
    message: str


class TailscaleBeaconCharm(ops.CharmBase):
    """Charm exposing related applications onto a tailnet via LoadBalancer Services."""

    def __init__(self, *args):
        super().__init__(*args)
        self._lightkube_field_manager = self.app.name
        self._lightkube_client: Optional[Client] = None

        self.ingress = IngressPerAppProvider(self, relation_name="ingress")

        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.start, self._reconcile)
        self.framework.observe(self.on.upgrade_charm, self._reconcile)
        self.framework.observe(self.on.update_status, self._reconcile)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.ingress.on.data_provided, self._reconcile)
        self.framework.observe(self.ingress.on.data_removed, self._reconcile)

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
    def _ready_timeout(self) -> int:
        """Max seconds to wait, within a hook, for a proxy's tailnet address."""
        return int(self.config.get("ready-timeout", 30))

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
        """Reconcile the whole desired state of the charm.

        Steps:
          1. Precondition — trust. Without it no cluster writes are possible.
          2. Services — one LoadBalancer Service per ingress relation.
          3. Publish — wait (bounded) for each proxy's tailnet address and publish
             the resulting URL back to the requirer.
          4. Deferred errors — raise for terminal proxy failures at the very end so
             the rest of the reconcile completes first.
        """
        if not self._trusted:
            logger.warning("Charm is not trusted; skipping reconciliation")
            return

        self._reconcile_services()
        errors = self._publish_ingress_urls()
        if errors:
            raise RuntimeError("; ".join(errors))

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Evaluate current state and add unit statuses."""
        if not self._trusted:
            event.add_status(
                ops.BlockedStatus(f"Trust not granted. Run 'juju trust {self.app.name}'")
            )
            return

        ready = self._ready_ingress_data()
        if not ready:
            event.add_status(ops.ActiveStatus())
            return

        states = [
            (data, self._proxy_state(data.app.name, data.app.model))
            for _relation, data in ready
        ]
        if any(state.error for _data, state in states):
            event.add_status(ops.BlockedStatus("One or more tailnet proxies failed"))
            return
        if any(not state.hostname for _data, state in states):
            event.add_status(ops.WaitingStatus("Waiting for tailnet proxies to become ready"))
            return

        tailnet = next(
            (self._tailnet_name(state.hostname) for _data, state in states if state.hostname),
            None,
        )
        event.add_status(
            ops.ActiveStatus(f"Connected to tailnet {tailnet}" if tailnet else "")
        )

    def _on_remove(self, _event: ops.RemoveEvent):
        """Tear down the charm's resources when the last unit is removed."""
        if self.app.planned_units() != 0:
            logger.info("Unit removed but application remains; leaving resources in place")
            return
        self._service_krm().delete(ignore_missing=True)

    def _reconcile_services(self):
        """Create one LoadBalancer Service per ingress relation."""
        services: LightkubeResourcesList = [
            self._build_service(data.app.name, data.app.model, data.app.port)
            for _relation, data in self._ready_ingress_data()
        ]
        self._service_krm().reconcile(services)

    def _build_service(self, app_name: str, namespace: str, port: int) -> Service:
        """Build the LoadBalancer Service that exposes an app on the tailnet.

        The Service lives in the app's own namespace so its selector matches the
        app's pods, and carries `loadBalancerClass: tailscale` so the cluster-wide
        Tailscale operator (not the cluster's default load balancer) reconciles it.
        """
        return Service(
            metadata=ObjectMeta(
                name=self._service_name(app_name),
                namespace=namespace,
                annotations={TAILSCALE_HOSTNAME_ANNOTATION: self._hostname(app_name, namespace)},
            ),
            spec=ServiceSpec(
                type="LoadBalancer",
                loadBalancerClass=TAILSCALE_LOAD_BALANCER_CLASS,
                selector={"app.kubernetes.io/name": app_name},
                ports=[ServicePort(port=port)],
            ),
        )

    def _publish_ingress_urls(self) -> List[str]:
        """Publish tailnet URLs to requirers, returning terminal error messages.

        Waits (within the hook, up to `ready-timeout`) for every proxy's tailnet
        address to appear so the common case publishes promptly. A proxy that is
        merely slow (still ProxyPending) is left unpublished and surfaced as a
        WaitingStatus by `_on_collect_status`; only terminal proxy failures are
        returned here to be raised after the reconcile completes.
        """
        ready = self._ready_ingress_data()
        if not ready:
            return []

        deadline = time.monotonic() + self._ready_timeout
        states = {}
        while True:
            states = {
                relation.id: self._proxy_state(data.app.name, data.app.model)
                for relation, data in ready
            }
            unresolved = [
                relation for relation, _data in ready if states[relation.id].pending
            ]
            if not unresolved or time.monotonic() >= deadline:
                break
            time.sleep(_POLL_INTERVAL_SECONDS)

        errors: List[str] = []
        pending: List[str] = []
        for relation, data in ready:
            state = states[relation.id]
            if state.hostname:
                self.ingress.publish_url(
                    relation, f"http://{state.hostname}:{data.app.port}/"
                )
                continue

            self.ingress.wipe_ingress_data(relation)
            if state.error:
                logger.error(
                    "Tailscale proxy for %r failed: %s", data.app.name, state.message
                )
                errors.append(f"{data.app.name}: {state.message}")
            else:
                pending.append(data.app.name)

        if pending:
            logger.warning(
                "Tailscale proxies still not ready after %ss: %s. If they never become "
                "ready, check the tailnet admin console for devices awaiting approval "
                "(NeedsMachineAuth).",
                self._ready_timeout,
                ", ".join(sorted(pending)),
            )
        return errors

    def _proxy_state(self, app_name: str, namespace: str) -> _ProxyState:
        """Derive the beacon's view of an app from its Service status."""
        try:
            svc = self.lightkube_client.get(
                Service, name=self._service_name(app_name), namespace=namespace
            )
        except ApiError as e:
            if e.status.code == 404:
                return _ProxyState(
                    hostname=None,
                    pending=True,
                    error=False,
                    message="waiting for LoadBalancer Service to be created",
                )
            raise

        reason, message = self._proxy_ready_condition(svc)
        if reason in PROXY_ERROR_REASONS:
            message = message or "the Tailscale operator reported a proxy failure"
            return _ProxyState(hostname=None, pending=False, error=True, message=message)

        hostname = self._extract_hostname(svc)
        if hostname:
            return _ProxyState(hostname=hostname, pending=False, error=False, message="")

        message = message or "waiting for the Tailscale operator to provision the proxy"
        return _ProxyState(hostname=None, pending=True, error=False, message=message)

    @staticmethod
    def _extract_hostname(svc: Service) -> Optional[str]:
        """Return the tailnet hostname from the Service's LB status, if populated."""
        status = getattr(svc, "status", None)
        load_balancer = getattr(status, "loadBalancer", None) if status else None
        ingress = getattr(load_balancer, "ingress", None) if load_balancer else None
        for entry in ingress or []:
            hostname = getattr(entry, "hostname", None) or getattr(entry, "ip", None)
            if hostname:
                return hostname
        return None

    @staticmethod
    def _proxy_ready_condition(svc: Service) -> Tuple[Optional[str], str]:
        """Return (reason, message) of the operator's ProxyReady condition, if any."""
        status = getattr(svc, "status", None)
        conditions = getattr(status, "conditions", None) if status else None
        for condition in conditions or []:
            if getattr(condition, "type", None) == PROXY_READY_CONDITION:
                return getattr(condition, "reason", None), getattr(condition, "message", "") or ""
        return None, ""

    @staticmethod
    def _tailnet_name(hostname: str) -> str:
        """Derive the tailnet name from a MagicDNS hostname (`<device>.<tailnet>`)."""
        _device, _, tailnet = hostname.partition(".")
        return tailnet or hostname

    def _ready_ingress_data(self) -> List[Tuple[ops.Relation, IngressRequirerData]]:
        """Return [(relation, IngressRequirerData)] for every ready ingress relation."""
        ready = []
        for relation in self.model.relations["ingress"]:
            if not self.ingress.is_ready(relation):
                continue
            ready.append((relation, self.ingress.get_data(relation)))
        return ready

    @staticmethod
    def _service_name(app_name: str) -> str:
        return f"{app_name}-tailscale"

    @staticmethod
    def _hostname(app_name: str, model: str) -> str:
        """Return the tailnet device hostname for an app.

        Qualified with the model so it is unique across the tailnet, matching the
        ``{model}-{app}`` order Traefik uses for its default ingress path prefix.
        """
        return f"{model}-{app_name}"

    def _service_krm(self) -> KubernetesResourceManager:
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=SERVICE_SCOPE
            ),
            resource_types={Service},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )


if __name__ == "__main__":
    ops.main(TailscaleBeaconCharm)
