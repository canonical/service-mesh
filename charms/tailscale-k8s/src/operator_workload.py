# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pebble workload management for the Tailscale K8s operator charm.

Handles building the Pebble layer and pushing credentials to the container.
"""

import ops
from ops.pebble import Layer

OAUTH_DIR = "/oauth"
OPERATOR_SERVICE = "tailscale-operator"


def build_pebble_layer(
    *,
    namespace: str,
    operator_tags: str,
    proxy_tags: str,
    login_server: str,
) -> Layer:
    """Build the Pebble layer for the Tailscale operator.

    Args:
        namespace: The Kubernetes namespace for the operator.
        operator_tags: Comma-separated tags for the operator device.
        proxy_tags: Comma-separated tags for proxy pods.
        login_server: The control plane URL (empty for Tailscale SaaS).
    """
    env = {
        "CLIENT_ID_FILE": f"{OAUTH_DIR}/client_id",
        "CLIENT_SECRET_FILE": f"{OAUTH_DIR}/client_secret",
        "OPERATOR_INITIAL_TAGS": operator_tags,
        "PROXY_TAGS": proxy_tags,
        "OPERATOR_HOSTNAME": f"tailscale-operator-{namespace}",
        "OPERATOR_NAMESPACE": namespace,
        "APISERVER_PROXY": "false",
        "PROXY_FIREWALL_MODE": "auto",
        "POD_IP": "",
        # Override the Kubernetes-injected service-link env var. When the app is
        # deployed with a name that uppercases to "TS" (e.g. `juju deploy ... ts`),
        # Kubernetes injects the Docker-link legacy var TS_PORT=tcp://<ip>:<port>
        # for the app's Service. The operator reads TS_PORT as its tailscaled
        # listen port and fatals parsing it as a uint16. Pinning it here makes the
        # operator's own value win regardless of app name. "0" == unset -> tsnet
        # auto-selects the port.
        "TS_PORT": "0",
    }

    if login_server:
        # The operator reads the control-plane URL from OPERATOR_LOGIN_SERVER
        # (see cmd/k8s-operator/operator.go: defaultEnv("OPERATOR_LOGIN_SERVER", "")).
        # It does NOT read TS_LOGIN_SERVER. The operator propagates this URL to
        # the proxy pods it spawns via their generated config.
        env["OPERATOR_LOGIN_SERVER"] = login_server

    return Layer(
        {
            "summary": "Tailscale Operator Layer",
            "description": "Pebble layer for the Tailscale Kubernetes operator",
            "services": {
                OPERATOR_SERVICE: {
                    "override": "replace",
                    "summary": "Tailscale K8s Operator",
                    "command": "/usr/local/bin/operator",
                    "startup": "enabled",
                    "environment": env,
                }
            },
        }
    )


def push_credentials(container: ops.Container, credentials: dict):
    """Push OAuth credentials to the container filesystem.

    Args:
        container: The Pebble container to write to.
        credentials: Dict with 'client-id' and 'client-secret' keys.
    """
    container.push(f"{OAUTH_DIR}/client_id", credentials["client-id"], make_dirs=True)
    container.push(f"{OAUTH_DIR}/client_secret", credentials["client-secret"], make_dirs=True)
