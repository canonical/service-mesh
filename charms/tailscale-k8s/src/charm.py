#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing the Tailscale Kubernetes operator."""

import logging

import ops
from canonical_service_mesh.k8s.resource_manager import (
    KubernetesResourceManager,
    create_charm_default_labels,
)
from lightkube import Client

from credentials import resolve_credentials
from k8s_resources import (
    CRD_RESOURCE_TYPES,
    OPERATOR_RESOURCE_TYPES,
    SCOPE_CRDS,
    SCOPE_OPERATOR,
    build_crd_resources,
    build_operator_resources,
    detect_existing_operator,
    get_namespace_owner_reference,
)
from operator_workload import OPERATOR_SERVICE, build_pebble_layer, push_credentials

LOGGER = logging.getLogger(__name__)

OPERATOR_CONTAINER = "tailscale-operator"


class TailscaleK8sCharm(ops.CharmBase):
    """Charm for managing the Tailscale Kubernetes operator."""

    def __init__(self, *args):
        super().__init__(*args)

        # Holistic reconciliation: every state-changing event converges to the
        # same _reconcile. Only collect_unit_status (a read-only status hook) is
        # handled separately.
        for event in (
            self.on.install,
            self.on.start,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on.update_status,
            self.on.secret_changed,
            self.on.tailscale_operator_pebble_ready,
            self.on.remove,
        ):
            self.framework.observe(event, self._reconcile)

        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)

    # --- Properties ---

    @property
    def _namespace(self) -> str:
        """Return the model namespace."""
        return self.model.name

    @property
    def _lightkube_client(self) -> Client:
        """Return a lightkube client."""
        return Client(namespace=self._namespace, field_manager=self.app.name)

    @property
    def _container(self) -> ops.Container:
        """Return the Pebble container for the operator."""
        return self.unit.get_container(OPERATOR_CONTAINER)

    @property
    def _is_scaled_beyond_one(self) -> bool:
        """Check if the application has been scaled beyond 1 replica."""
        return self.app.planned_units() > 1

    @property
    def _login_server(self) -> str:
        """Return the login server URL from config."""
        return str(self.config.get("login-server", ""))

    @property
    def _operator_tags(self) -> str:
        """Return operator tags from config."""
        return str(self.config.get("operator-tags", "tag:k8s-operator"))

    @property
    def _proxy_tags(self) -> str:
        """Return proxy tags from config."""
        return str(self.config.get("proxy-tags", "tag:k8s"))

    @property
    def _instance_label(self) -> str:
        """Return this charm's app.kubernetes.io/instance label value."""
        return create_charm_default_labels(
            self.app.name, self.model.name, scope=SCOPE_OPERATOR
        )["app.kubernetes.io/instance"]

    # --- Kubernetes resource managers ---

    def _resource_manager(self, scope: str, resource_types) -> KubernetesResourceManager:
        """Return a KubernetesResourceManager for the given resource group."""
        return KubernetesResourceManager(
            labels=create_charm_default_labels(
                self.app.name, self.model.name, scope=scope
            ),
            resource_types=resource_types,
            lightkube_client=self._lightkube_client,
            logger=LOGGER,
        )

    def _reconcile_k8s_resources(self):
        """Apply (and garbage-collect) the charm-managed Kubernetes resources.

        CRDs and operator-support resources are managed as separate KRM groups.
        Both are reconciled here; only the operator-support group is torn down on
        removal (CRDs are left in place to avoid cascading deletes of user
        ProxyGroups/Connectors).

        The IngressClass is cluster-scoped, so it is given an OwnerReference to
        the model Namespace: Kubernetes then garbage-collects it when the
        namespace is deleted (e.g. `destroy-model`, including `--force` which
        skips charm hooks). This backstops the reconcile teardown, which only
        covers `remove-application`. See k8s_resources.get_namespace_owner_reference.
        """
        self._resource_manager(SCOPE_CRDS, CRD_RESOURCE_TYPES).reconcile(
            build_crd_resources()
        )
        owner = get_namespace_owner_reference(self._lightkube_client, self._namespace)
        self._resource_manager(SCOPE_OPERATOR, OPERATOR_RESOURCE_TYPES).reconcile(
            build_operator_resources(self._namespace, ingressclass_owner=owner)
        )

    # --- Event handlers ---

    def _reconcile(self, _event):
        """Converge the charm to its desired state.

        Every state-changing event routes here. The flow is a straight line:
        bail out early on the conditions we can't/shouldn't act on, ensure the
        Kubernetes resources exist, then (once credentials are available) start
        the operator.
        """
        if not self.unit.is_leader():
            return

        # planned_units() == 0 means the application is being removed. Juju GCs
        # the namespaced resources it labels, but not the cluster-scoped
        # IngressClass, so tear the operator group down here (namespaced deletes
        # are harmless no-ops). This replaces a dedicated remove handler.
        if self.app.planned_units() == 0:
            LOGGER.info("Application is being removed; cleaning up Kubernetes resources")
            try:
                self._resource_manager(SCOPE_OPERATOR, OPERATOR_RESOURCE_TYPES).delete()
            except Exception as e:
                LOGGER.error("Failed to delete Kubernetes resources: %s", e)
            return

        if self._is_scaled_beyond_one:
            return

        if detect_existing_operator(self._lightkube_client, self._instance_label):
            return

        # Ensure the Kubernetes resources exist before we need them. This runs
        # regardless of credentials so the operator's prerequisites (CRDs, proxy
        # RBAC, IngressClass) are in place from install onwards.
        try:
            self._reconcile_k8s_resources()
        except Exception as e:
            LOGGER.error("Failed to ensure Kubernetes resources: %s", e)
            return

        credentials, error = resolve_credentials(self)
        if error:
            LOGGER.info("Credentials not ready: %s", error)
            return

        container = self._container
        if not container.can_connect():
            LOGGER.info("Waiting for Pebble to be ready")
            return

        push_credentials(container, credentials)

        layer = build_pebble_layer(
            namespace=self._namespace,
            operator_tags=self._operator_tags,
            proxy_tags=self._proxy_tags,
            login_server=self._login_server,
        )
        container.add_layer("tailscale-operator", layer, combine=True)
        try:
            container.replan()
        except ops.pebble.ChangeError as e:
            LOGGER.error("Failed to start operator service: %s", e)
            return

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Collect unit status."""
        if not self.unit.is_leader():
            event.add_status(ops.ActiveStatus("Standby (non-leader)"))
            return

        if self._is_scaled_beyond_one:
            event.add_status(
                ops.BlockedStatus(
                    "Tailscale operator does not support multiple replicas"
                )
            )
            return

        if detect_existing_operator(self._lightkube_client, self._instance_label):
            event.add_status(
                ops.BlockedStatus(
                    "Another Tailscale operator detected on this cluster"
                )
            )
            return

        _credentials, error = resolve_credentials(self)
        if error:
            event.add_status(ops.BlockedStatus(error))
            return

        container = self._container
        if not container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble to be ready"))
            return

        try:
            service = container.get_service(OPERATOR_SERVICE)
            if not service.is_running():
                event.add_status(ops.WaitingStatus("Operator service not yet running"))
                return
        except (ops.pebble.APIError, ops.ModelError):
            event.add_status(ops.WaitingStatus("Operator service not configured"))
            return

        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":
    ops.main.main(TailscaleK8sCharm)
