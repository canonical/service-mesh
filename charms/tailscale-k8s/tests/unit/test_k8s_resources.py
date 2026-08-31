#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for Kubernetes resource definitions and reconciliation."""

from unittest.mock import MagicMock, patch

from conftest import _make_api_error
from lightkube.models.meta_v1 import OwnerReference
from scenario import Container, Context, State

from charm import TailscaleK8sCharm
from k8s_resources import (
    INGRESS_CLASS_NAME,
    PROXIES_SA_NAME,
    SCOPE_CRDS,
    SCOPE_OPERATOR,
    build_crd_resources,
    build_operator_resources,
    get_namespace_owner_reference,
)


class TestBuildResources:
    """Test the pure resource-builder functions."""

    def test_build_operator_resources(self):
        """Operator group should be SA + Role + RoleBinding + IngressClass."""
        resources = build_operator_resources("mymodel")
        kinds = {type(r).__name__ for r in resources}
        assert kinds == {"ServiceAccount", "Role", "RoleBinding", "IngressClass"}

        by_kind = {type(r).__name__: r for r in resources}
        assert by_kind["ServiceAccount"].metadata.name == PROXIES_SA_NAME
        assert by_kind["ServiceAccount"].metadata.namespace == "mymodel"
        assert by_kind["IngressClass"].metadata.name == INGRESS_CLASS_NAME
        assert by_kind["IngressClass"].spec["controller"] == "tailscale.com/ts-ingress"

    def test_operator_role_rules(self):
        """The proxies Role must grant secrets CRUD and events."""
        role = next(r for r in build_operator_resources("m") if type(r).__name__ == "Role")
        rules = {tuple(rule.resources): set(rule.verbs) for rule in role.rules}
        assert ("secrets",) in rules
        assert rules[("secrets",)] == {
            "create", "get", "list", "watch", "update", "patch", "delete"
        }
        assert ("events",) in rules

    def test_rolebinding_targets_proxies(self):
        """RoleBinding must bind the proxies SA to the proxies Role."""
        rb = next(
            r for r in build_operator_resources("m") if type(r).__name__ == "RoleBinding"
        )
        assert rb.roleRef.name == PROXIES_SA_NAME
        assert rb.roleRef.kind == "Role"
        assert rb.subjects[0].name == PROXIES_SA_NAME
        assert rb.subjects[0].namespace == "m"

    def test_build_crd_resources(self):
        """All seven bundled Tailscale CRDs should be loaded."""
        crds = build_crd_resources()
        assert len(crds) == 7
        names = {c.metadata.name for c in crds}
        assert "connectors.tailscale.com" in names
        assert "proxygroups.tailscale.com" in names
        assert all(type(c).__name__ == "CustomResourceDefinition" for c in crds)


class TestNamespaceOwnerReference:
    """Test the cluster-scoped IngressClass owner-ref (GC safety net)."""

    def test_owner_reference_from_namespace(self):
        """A valid namespace yields an OwnerReference carrying its UID."""
        client = MagicMock()
        client.get.return_value.metadata.uid = "ns-uid-123"
        ref = get_namespace_owner_reference(client, "mymodel")
        assert ref is not None
        assert ref.kind == "Namespace"
        assert ref.name == "mymodel"
        assert ref.uid == "ns-uid-123"
        assert ref.blockOwnerDeletion is False
        assert ref.controller is False

    def test_owner_reference_none_on_apierror(self):
        """If the namespace can't be read, no owner-ref is produced."""
        client = MagicMock()
        client.get.side_effect = _make_api_error(404)
        assert get_namespace_owner_reference(client, "mymodel") is None

    def test_ingressclass_gets_owner_ref_but_namespaced_do_not(self):
        """Only the cluster-scoped IngressClass carries the owner-ref."""
        ref = OwnerReference(apiVersion="v1", kind="Namespace", name="m", uid="u")
        resources = build_operator_resources("m", ingressclass_owner=ref)
        by_kind = {type(r).__name__: r for r in resources}
        assert by_kind["IngressClass"].metadata.ownerReferences == [ref]
        # Namespaced resources are Juju-GC'd and must not get a (invalid) owner-ref.
        assert by_kind["ServiceAccount"].metadata.ownerReferences is None
        assert by_kind["Role"].metadata.ownerReferences is None
        assert by_kind["RoleBinding"].metadata.ownerReferences is None

    def test_ingressclass_no_owner_ref_when_unavailable(self):
        """Without an owner-ref, the IngressClass is created plain (fallback)."""
        resources = build_operator_resources("m")
        ic = next(r for r in resources if type(r).__name__ == "IngressClass")
        assert ic.metadata.ownerReferences is None


class TestResourceReconciliation:
    """Test that the charm drives the KubernetesResourceManager correctly."""

    def _run(self, event_name, *, leader=True, existing_operator=False, planned_units=1):
        """Run an event with KubernetesResourceManager patched; return the mock class."""
        container = Container(name="tailscale-operator", can_connect=False)
        with patch("charm.Client") as mock_client_cls, patch(
            "charm.KubernetesResourceManager"
        ) as mock_krm_cls, patch("charm.detect_existing_operator") as mock_detect:
            mock_client_cls.return_value = MagicMock()
            mock_detect.return_value = existing_operator

            ctx = Context(charm_type=TailscaleK8sCharm)
            state = State(leader=leader, containers=[container], planned_units=planned_units)
            ctx.run(getattr(ctx.on, event_name)(), state)
            return mock_krm_cls

    def test_install_reconciles_both_groups(self):
        """Install should reconcile the CRDs and operator resource groups."""
        krm = self._run("install")
        # A KRM is created per group (crds + operator) and reconcile() called on each.
        assert krm.return_value.reconcile.call_count == 2
        scopes = {
            c.kwargs["labels"]["kubernetes-resource-handler-scope"]
            for c in krm.call_args_list
        }
        assert scopes == {SCOPE_CRDS, SCOPE_OPERATOR}

    def test_install_skips_on_non_leader(self):
        """Non-leader should not manage resources."""
        krm = self._run("install", leader=False)
        krm.return_value.reconcile.assert_not_called()

    def test_install_skips_when_existing_operator(self):
        """Install with a foreign operator present should skip resource creation."""
        krm = self._run("install", existing_operator=True)
        krm.return_value.reconcile.assert_not_called()

    def test_remove_deletes_only_operator_group(self):
        """planned_units==0 (removal) should delete the operator group, not CRDs."""
        krm = self._run("remove", planned_units=0)
        krm.return_value.delete.assert_called_once()
        # The single KRM constructed on teardown must be the operator scope.
        scopes = [
            c.kwargs["labels"]["kubernetes-resource-handler-scope"]
            for c in krm.call_args_list
        ]
        assert scopes == [SCOPE_OPERATOR]

    def test_remove_skips_on_non_leader(self):
        """Non-leader should not delete resources."""
        krm = self._run("remove", leader=False, planned_units=0)
        krm.return_value.delete.assert_not_called()

    def test_reconcile_does_not_delete_when_units_remain(self):
        """A reconcile with units still planned must not tear resources down."""
        krm = self._run("config_changed", planned_units=1)
        krm.return_value.delete.assert_not_called()

    def test_reconcile_handles_resource_failure(self, tailscale_context):
        """A KRM failure during reconcile is caught and stops before Pebble config."""
        container = Container(name="tailscale-operator", can_connect=True)
        with patch("charm.KubernetesResourceManager") as mock_krm_cls:
            mock_krm_cls.return_value.reconcile.side_effect = Exception("boom")
            from scenario import Secret
            secret = Secret(
                tracked_content={"client-id": "id", "client-secret": "secret"},
                latest_content={"client-id": "id", "client-secret": "secret"},
                owner="app",
            )
            state = State(
                leader=True,
                containers=[container],
                planned_units=1,
                secrets=[secret],
                config={"credentials": secret.id},
            )
            out = tailscale_context.run(tailscale_context.on.config_changed(), state)
        # No pebble layer applied because resource reconcile failed first.
        assert "tailscale-operator" not in out.get_container("tailscale-operator").layers


class TestExistingOperatorDetection:
    """Test detection of another Tailscale operator via the IngressClass label."""

    def _status_with_ingressclass(self, ingressclass, operator_container):
        from scenario import Secret
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        with patch("charm.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.list.return_value = []
            if ingressclass is None:
                mock_client.get.side_effect = _make_api_error(404)
            else:
                mock_client.get.return_value = ingressclass

            ctx = Context(charm_type=TailscaleK8sCharm)
            state = State(
                leader=True,
                containers=[operator_container],
                planned_units=1,
                secrets=[secret],
                config={"credentials": secret.id},
            )
            return ctx.run(ctx.on.collect_unit_status(), state)

    def test_blocked_when_foreign_ingressclass(self, operator_container):
        """An IngressClass owned by a different instance should block."""
        ic = MagicMock()
        ic.metadata = {"labels": {"app.kubernetes.io/instance": "other-model-other-app"}}
        out = self._status_with_ingressclass(ic, operator_container)
        assert "Another Tailscale operator" in out.unit_status.message

    def test_blocked_when_ingressclass_unlabelled(self, operator_container):
        """An IngressClass with no matching instance label is treated as foreign."""
        ic = MagicMock()
        ic.metadata = {"labels": {}}
        out = self._status_with_ingressclass(ic, operator_container)
        assert "Another Tailscale operator" in out.unit_status.message

    def test_not_blocked_when_no_ingressclass(self, operator_container):
        """No IngressClass at all should not block as 'another operator'."""
        out = self._status_with_ingressclass(None, operator_container)
        assert "Another Tailscale operator" not in (out.unit_status.message or "")
