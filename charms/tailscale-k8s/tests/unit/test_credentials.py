#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for credential resolution logic."""

from scenario import Container, Relation, Secret, State


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


def _relation_secret():
    """A remote-owned credential secret as distributed by tailscale-config."""
    return Secret(
        tracked_content={"auth-key": "tskey-client-abc", "client-id": "kCHILD001"},
    )


def _credentials_relation(secret, login_server="https://hs.example.com"):
    """A tailscale-credentials relation carrying the provider app data."""
    return Relation(
        "tailscale-credentials",
        remote_app_name="tailscale-config",
        remote_app_data={
            "secret_id": secret.id,
            "login_server": login_server,
            "tags": "tag:k8s-operator",
        },
    )


class TestRelationCredentials:
    """Test credential handling via the tailscale-credentials relation."""

    def test_relation_provides_credentials(self, tailscale_context):
        """A ready relation should push credentials and set the login server."""
        secret = _relation_secret()
        relation = _credentials_relation(secret)
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            relations=[relation],
        )
        out = tailscale_context.run(
            tailscale_context.on.relation_changed(relation), state
        )

        out_container = out.get_container("tailscale-operator")
        fs = out_container.get_filesystem(tailscale_context)
        assert (fs / "oauth" / "client_id").read_text() == "kCHILD001"
        assert (fs / "oauth" / "client_secret").read_text() == "tskey-client-abc"

        svc = out_container.layers["tailscale-operator"].services["tailscale-operator"]
        assert svc.environment["OPERATOR_LOGIN_SERVER"] == "https://hs.example.com"

    def test_relation_active_status(self, tailscale_context):
        """A ready relation should let the charm reach a non-blocked status."""
        secret = _relation_secret()
        relation = _credentials_relation(secret)
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            relations=[relation],
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status.name != "blocked"

    def test_relation_not_ready_blocks(self, tailscale_context, operator_container):
        """A related-but-empty provider databag should block waiting for data."""
        relation = Relation(
            "tailscale-credentials", remote_app_name="tailscale-config"
        )
        state = State(
            leader=True,
            containers=[operator_container],
            planned_units=1,
            relations=[relation],
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status.name == "blocked"
        assert "Waiting for credentials" in out.unit_status.message

    def test_both_sources_present_blocks(self, tailscale_context, operator_container):
        """Config credentials AND a relation present should block with a conflict."""
        config_secret = Secret(
            tracked_content={"client-id": "my-id", "client-secret": "my-secret"},
            latest_content={"client-id": "my-id", "client-secret": "my-secret"},
            owner="app",
        )
        relation_secret = _relation_secret()
        relation = _credentials_relation(relation_secret)
        state = State(
            leader=True,
            containers=[operator_container],
            planned_units=1,
            secrets=[config_secret, relation_secret],
            relations=[relation],
            config={"credentials": config_secret.id},
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status.name == "blocked"
        assert "Both" in out.unit_status.message

    def test_relation_invalid_secret_blocks(self, tailscale_context, operator_container):
        """A relation secret missing required fields should block."""
        secret = Secret(tracked_content={"auth-key": "tskey-client-abc"})
        relation = _credentials_relation(secret)
        state = State(
            leader=True,
            containers=[operator_container],
            planned_units=1,
            secrets=[secret],
            relations=[relation],
        )
        out = tailscale_context.run(tailscale_context.on.collect_unit_status(), state)
        assert out.unit_status.name == "blocked"
        assert "invalid" in out.unit_status.message
