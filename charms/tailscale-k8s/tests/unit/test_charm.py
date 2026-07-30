#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for charm-level orchestration (status, scaling, reconcile flow)."""


import ops
from ops.pebble import Layer
from scenario import Container, Secret, State


class TestScalingEnforcement:
    """Test that the charm blocks when scaled beyond 1 replica."""

    def test_blocked_when_scaled_beyond_one(self, tailscale_context, operator_container):
        """The charm should block when scaled beyond 1 unit."""
        state = State(leader=True, containers=[operator_container], planned_units=2)
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status == ops.BlockedStatus(
            "Tailscale operator does not support multiple replicas"
        )

    def test_not_blocked_at_single_replica(self, tailscale_context, operator_container):
        """The charm should not block for scaling at 1 unit."""
        state = State(leader=True, containers=[operator_container], planned_units=1)
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert "multiple replicas" not in (out.unit_status.message or "")


class TestNonLeader:
    """Test non-leader unit behavior."""

    def test_non_leader_active_standby(self, tailscale_context, operator_container):
        """Non-leader units should report active standby."""
        state = State(leader=False, containers=[operator_container], planned_units=1)
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status == ops.ActiveStatus("Standby (non-leader)")


class TestContainerReadiness:
    """Test Pebble container readiness checks."""

    def test_waiting_for_pebble(self, tailscale_context, operator_container_not_ready):
        """Container not ready should show WaitingStatus."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        state = State(
            leader=True,
            containers=[operator_container_not_ready],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Waiting for Pebble to be ready")


class TestServiceStatus:
    """Test operator service running status."""

    def _operator_layer(self):
        return Layer({
            "services": {
                "tailscale-operator": {
                    "override": "replace",
                    "command": "/usr/local/bin/operator",
                    "startup": "enabled",
                }
            }
        })

    def test_service_not_running_shows_waiting(self, tailscale_context):
        """When the operator service exists but is not running, show WaitingStatus."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        container = Container(
            name="tailscale-operator",
            can_connect=True,
            layers={"tailscale-operator": self._operator_layer()},
            service_statuses={"tailscale-operator": ops.pebble.ServiceStatus.INACTIVE},
        )
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Operator service not yet running")

    def test_service_running_shows_active(self, tailscale_context):
        """When the operator service is running, show ActiveStatus."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        container = Container(
            name="tailscale-operator",
            can_connect=True,
            layers={"tailscale-operator": self._operator_layer()},
            service_statuses={"tailscale-operator": ops.pebble.ServiceStatus.ACTIVE},
        )
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status == ops.ActiveStatus()

    def test_service_not_configured_shows_waiting(self, tailscale_context, operator_container):
        """When no layer defines the service, show WaitingStatus."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        state = State(
            leader=True,
            containers=[operator_container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status == ops.WaitingStatus("Operator service not configured")


class TestReconcileFlow:
    """Test the reconcile event handler flow."""

    def test_reconcile_skips_on_non_leader(self, tailscale_context):
        """Non-leader units should not reconcile."""
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(leader=False, containers=[container], planned_units=1)
        out = tailscale_context.run(tailscale_context.on.config_changed(), state)
        assert "tailscale-operator" not in out.get_container("tailscale-operator").layers

    def test_reconcile_skips_when_container_not_ready(self, tailscale_context):
        """Should skip Pebble configuration when container is not ready."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        container = Container(name="tailscale-operator", can_connect=False)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.config_changed(), state)
        assert "tailscale-operator" not in out.get_container("tailscale-operator").layers

    def test_reconcile_full_path_configures_pebble(self, tailscale_context):
        """Full reconcile should push credentials and configure Pebble layer."""
        secret = Secret(
            tracked_content={"client-id": "my-id", "client-secret": "my-secret"},
            latest_content={"client-id": "my-id", "client-secret": "my-secret"},
            owner="app",
        )
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.config_changed(), state)

        out_container = out.get_container("tailscale-operator")
        assert "tailscale-operator" in out_container.layers
        layer = out_container.layers["tailscale-operator"]
        assert "tailscale-operator" in layer.services

    def test_secret_changed_repushes_rotated_credentials(self, tailscale_context):
        """A secret-changed event should reconcile and push the rotated secret.

        This is the credential-rotation path: the holistic reconcile observes
        secret_changed, so a rotated client-secret propagates to the operator
        without waiting for an unrelated hook.
        """
        secret = Secret(
            tracked_content={"client-id": "my-id", "client-secret": "old-secret"},
            latest_content={"client-id": "my-id", "client-secret": "rotated-secret"},
            owner=None,
        )
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.secret_changed(secret), state)

        out_container = out.get_container("tailscale-operator")
        assert "tailscale-operator" in out_container.layers
        fs = out_container.get_filesystem(tailscale_context)
        assert (fs / "oauth" / "client_secret").read_text() == "rotated-secret"
