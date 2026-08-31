#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for Pebble workload management (layer construction, credential pushing)."""

from unittest.mock import MagicMock, patch

import ops
from conftest import _make_api_error
from scenario import Container, Context, Secret, State

from charm import TailscaleK8sCharm


class TestPebbleLayerConstruction:
    """Test Pebble layer construction with various config settings."""

    def test_layer_has_correct_command(self, tailscale_context):
        """The Pebble layer should use the correct operator command."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
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

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert svc.command == "/usr/local/bin/operator"
        assert svc.environment["APISERVER_PROXY"] == "false"

    def test_ts_port_override(self, tailscale_context):
        """TS_PORT is pinned so a Kubernetes-injected service-link var can't shadow it.

        When the app is named "ts", Kubernetes injects TS_PORT=tcp://<ip>:<port>
        for the app's Service, which the operator otherwise fatals parsing as a
        uint16. Pinning "0" (== unset -> tsnet auto-selects) makes our value win.
        """
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
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

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert svc.environment["TS_PORT"] == "0"

    def test_default_tags(self, tailscale_context):
        """Default tags should be tag:k8s-operator and tag:k8s."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
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

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert svc.environment["OPERATOR_INITIAL_TAGS"] == "tag:k8s-operator"
        assert svc.environment["PROXY_TAGS"] == "tag:k8s"

    def test_custom_tags(self, tailscale_context):
        """Custom operator-tags and proxy-tags should be reflected."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={
                "credentials": secret.id,
                "operator-tags": "tag:custom-operator",
                "proxy-tags": "tag:custom-proxy,tag:extra",
            },
        )
        out = tailscale_context.run(tailscale_context.on.config_changed(), state)

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert svc.environment["OPERATOR_INITIAL_TAGS"] == "tag:custom-operator"
        assert svc.environment["PROXY_TAGS"] == "tag:custom-proxy,tag:extra"

    def test_login_server_from_config(self, tailscale_context):
        """Custom login-server config should set OPERATOR_LOGIN_SERVER."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        container = Container(name="tailscale-operator", can_connect=True)
        state = State(
            leader=True,
            containers=[container],
            planned_units=1,
            secrets=[secret],
            config={"credentials": secret.id, "login-server": "https://hs.example.com"},
        )
        out = tailscale_context.run(tailscale_context.on.config_changed(), state)

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert svc.environment["OPERATOR_LOGIN_SERVER"] == "https://hs.example.com"

    def test_no_login_server_env_when_empty(self, tailscale_context):
        """When login-server is empty, OPERATOR_LOGIN_SERVER should not be in env."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
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

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert "OPERATOR_LOGIN_SERVER" not in svc.environment

    def test_namespace_set_in_environment(self, tailscale_context):
        """OPERATOR_NAMESPACE should be set to the model name."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
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

        layer = out.get_container("tailscale-operator").layers["tailscale-operator"]
        svc = layer.services["tailscale-operator"]
        assert svc.environment["OPERATOR_NAMESPACE"] != ""
        assert svc.environment["CLIENT_ID_FILE"] == "/oauth/client_id"
        assert svc.environment["CLIENT_SECRET_FILE"] == "/oauth/client_secret"


class TestPebbleReconcileErrors:
    """Test error paths during Pebble reconciliation."""

    def test_reconcile_handles_pebble_change_error(self, tailscale_context):
        """ChangeError from replan should be caught gracefully."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
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
        with patch("ops.model.Container.replan") as mock_replan:
            mock_change = MagicMock()
            mock_change.err = "service failed to start"
            mock_replan.side_effect = ops.pebble.ChangeError("cannot start", mock_change)
            out = tailscale_context.run(tailscale_context.on.config_changed(), state)

        # Layer is still added even though replan failed
        out_container = out.get_container("tailscale-operator")
        assert "tailscale-operator" in out_container.layers

    def test_reconcile_handles_k8s_resource_failure(self, tailscale_context):
        """Resource reconciliation failure should prevent Pebble configuration."""
        secret = Secret(
            tracked_content={"client-id": "id", "client-secret": "secret"},
            latest_content={"client-id": "id", "client-secret": "secret"},
            owner="app",
        )
        container = Container(name="tailscale-operator", can_connect=True)

        with patch("charm.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get.side_effect = _make_api_error(404)
            mock_client.list.return_value = []
            # KubernetesResourceManager applies via client.patch; make it fail.
            mock_client.patch.side_effect = _make_api_error(403)

            ctx = Context(charm_type=TailscaleK8sCharm)
            state = State(
                leader=True,
                containers=[container],
                planned_units=1,
                secrets=[secret],
                config={"credentials": secret.id},
            )
            out = ctx.run(ctx.on.config_changed(), state)

        # No layer should be applied since resource creation failed before Pebble step
        out_container = out.get_container("tailscale-operator")
        assert "tailscale-operator" not in out_container.layers
