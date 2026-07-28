#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for credential resolution logic."""

from scenario import Container, Secret, State


class TestNoCredentials:
    """Test that the charm blocks when no credentials are configured."""

    def test_blocked_without_credentials(self, tailscale_context, operator_container):
        """No credentials at all should cause BlockedStatus."""
        state = State(
            leader=True, containers=[operator_container], planned_units=1,
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status.name == "blocked"
        assert "No credentials" in out.unit_status.message


class TestManualCredentials:
    """Test manual credential handling via Juju secrets."""

    def test_valid_secret_provides_credentials(self, tailscale_context):
        """A valid secret with both fields should allow reconciliation."""
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

        # Credentials should be pushed to the container
        out_container = out.get_container("tailscale-operator")
        fs = out_container.get_filesystem(tailscale_context)
        assert (fs / "oauth" / "client_id").read_text() == "my-id"
        assert (fs / "oauth" / "client_secret").read_text() == "my-secret"

    def test_secret_with_empty_client_id(self, tailscale_context, operator_container):
        """Secret with empty client-id should block naming the missing field."""
        secret = Secret(
            tracked_content={"client-id": "", "client-secret": "my-secret"},
            latest_content={"client-id": "", "client-secret": "my-secret"},
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
        assert out.unit_status.name == "blocked"
        assert "missing required field" in out.unit_status.message
        assert "client-id" in out.unit_status.message

    def test_secret_with_empty_client_secret(self, tailscale_context, operator_container):
        """Secret with empty client-secret should block naming the missing field."""
        secret = Secret(
            tracked_content={"client-id": "my-id", "client-secret": ""},
            latest_content={"client-id": "my-id", "client-secret": ""},
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
        assert out.unit_status.name == "blocked"
        assert "missing required field" in out.unit_status.message
        assert "client-secret" in out.unit_status.message
