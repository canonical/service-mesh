#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests using a real Headscale control plane.

These tests deploy Headscale on the same cluster, create OAuth credentials,
and verify the Tailscale K8s operator registers successfully. They also test
that workloads exposed via LoadBalancer Services are reachable over the tailnet.
"""

import json
import logging
import os
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    "tailscale-operator-image": METADATA["resources"]["tailscale-operator-image"][
        "upstream-source"
    ],
}

# NOTE: We deploy Headscale from a raw `main` image rather than the
# `headscale-k8s` charm on purpose.
#
# The Tailscale Kubernetes operator can only drive Headscale once Headscale
# implements the Tailscale-compatible v2 API with OAuth clients + scopes
# (juanfont/headscale PR #3334, "OAuth clients and scopes for the v2 API").
# That feature ships in Headscale >= v0.30.0, which is NOT released yet — it
# currently exists only on `main`. Hence the `main-*` pin and the use of the
# `headscale oauth-clients create` CLI below (both require v0.30.0+).
#
# The `headscale-k8s` charm (rev 14) predates this and exposes only pre-auth
# key actions (create/expire/list-authkey), so it cannot authenticate the
# operator today.
#
# TODO: switch this test to deploy the `headscale-k8s` charm once it ships
# Headscale >= v0.30.0 (tracking issue filed against the charm to bump it).
#
# TLS / DERP note: we serve Headscale over plain HTTP and use its embedded DERP
# over HTTP, mirroring upstream's own operator test
# (juanfont/headscale integration TestK8sOperator, integration/k3sic). This
# avoids TLS entirely: the operator + proxy pods need no CA. (A private-CA TLS
# Headscale is NOT viable here because a CA cannot be injected into proxy pods —
# see integration/k3sic/tls-ca-baking.md upstream — which is why the charm has
# no custom-CA option.) Proxy pods reach the non-TLS embedded DERP via a
# ProxyClass that sets TS_DEBUG_DERP_WS_CLIENT + TS_DEBUG_USE_DERP_HTTP.
HEADSCALE_IMAGE = "docker.io/headscale/headscale:main-f20f1f1"
HEADSCALE_NAME = "headscale"
HTTPBIN_NAME = "httpbin"
# ProxyClass that switches proxy pods to plain-HTTP websocket DERP so they can
# reach Headscale's non-TLS embedded DERP (cluster-scoped; selected via the
# tailscale.com/proxy-class label on the exposed Service).
DERP_WS_PROXYCLASS = "headscale-derp-ws"


def create_derp_ws_proxyclass():
    """Create the ProxyClass that makes proxies use plain-HTTP websocket DERP."""
    manifest = f"""
apiVersion: tailscale.com/v1alpha1
kind: ProxyClass
metadata:
  name: {DERP_WS_PROXYCLASS}
spec:
  statefulSet:
    pod:
      tailscaleContainer:
        env:
        - name: TS_DEBUG_DERP_WS_CLIENT
          value: "true"
        - name: TS_DEBUG_USE_DERP_HTTP
          value: "true"
"""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"kubectl apply ProxyClass failed: {result.stderr}"


def kubectl(*args, namespace=None):
    """Run a kubectl command and return (returncode, stdout, stderr)."""
    cmd = ["kubectl"]
    if namespace:
        cmd += ["-n", namespace]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def kubectl_apply(manifest: str, namespace: str):
    """Apply a YAML manifest via kubectl."""
    result = subprocess.run(
        ["kubectl", "apply", "-n", namespace, "-f", "-"],
        input=manifest, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"kubectl apply failed: {result.stderr}"


def wait_for_deployment(name: str, namespace: str, timeout: int = 120):
    """Wait for a deployment to be available."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc, out, _ = kubectl(
            "get", "deployment", name, "-o",
            "jsonpath={.status.availableReplicas}", namespace=namespace,
        )
        if rc == 0 and out.strip() == "1":
            return
        time.sleep(5)
    raise TimeoutError(f"Deployment {name} not ready within {timeout}s")


def headscale_exec(namespace: str, *cmd):
    """Execute a command inside the headscale pod."""
    rc, pod_name, _ = kubectl(
        "get", "pod", "-l", f"app={HEADSCALE_NAME}",
        "-o", "jsonpath={.items[0].metadata.name}",
        namespace=namespace,
    )
    assert rc == 0 and pod_name, "Could not find headscale pod"
    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name, "--", *cmd],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def deploy_headscale(namespace: str) -> str:
    """Deploy Headscale over plain HTTP with an embedded (non-TLS) DERP server.

    Mirrors upstream's operator test: no TLS, so the operator and proxy pods
    need no CA. server_url must be an address clients actually dial, so we create
    the Service first, read its ClusterIP, and bake http://<clusterIP>:8080 into
    the config (an IP endpoint also sidesteps control-plane hostname/port dial
    quirks). Returns the http://<ip>:8080 login-server URL.
    """
    # 1. Create the Service first so we can learn its ClusterIP.
    svc_manifest = f"""
apiVersion: v1
kind: Service
metadata:
  name: {HEADSCALE_NAME}
spec:
  selector:
    app: {HEADSCALE_NAME}
  ports:
  - name: http
    port: 8080
    targetPort: 8080
  - name: stun
    port: 3478
    protocol: UDP
    targetPort: 3478
"""
    kubectl_apply(svc_manifest, namespace)
    rc, cluster_ip, err = kubectl(
        "get", "svc", HEADSCALE_NAME, "-o", "jsonpath={.spec.clusterIP}",
        namespace=namespace,
    )
    assert rc == 0 and cluster_ip.strip(), f"Could not read headscale ClusterIP: {err}"
    cluster_ip = cluster_ip.strip()
    server_url = f"http://{cluster_ip}:8080"

    config = {
        "server_url": server_url,
        "listen_addr": "0.0.0.0:8080",
        "metrics_listen_addr": "0.0.0.0:9090",
        "database": {
            "type": "sqlite3",
            "sqlite": {"path": "/var/lib/headscale/db.sqlite"},
        },
        "prefixes": {
            "v4": "100.64.0.0/10",
            "v6": "fd7a:115c:a1e0::/48",
        },
        "dns": {
            "magic_dns": False,
            "override_local_dns": False,
            "base_domain": "tailnet.local",
        },
        # Embedded DERP served over the same plain-HTTP listener (no TLS). Proxy
        # pods reach it via websocket DERP (see DERP_WS_PROXYCLASS).
        "derp": {
            "server": {
                "enabled": True,
                "region_id": 999,
                "region_code": "headscale",
                "region_name": "Headscale Embedded DERP",
                "stun_listen_addr": "0.0.0.0:3478",
                "private_key_path": "/var/lib/headscale/derp_server_private.key",
                "automatically_add_embedded_derp_region": True,
            },
            "urls": [],
            "auto_update_enabled": False,
        },
        "noise": {
            "private_key_path": "/var/lib/headscale/noise_private.key",
        },
        # Load the ACL policy (incl. tagOwners) from a file mounted via the
        # ConfigMap. The headscale image is distroless (no shell) and its
        # filesystem is read-only, so we cannot write a policy file into the
        # pod or use `headscale policy set --file` at runtime; mounting it and
        # using policy.mode=file is the reliable path.
        "policy": {
            "mode": "file",
            "path": "/etc/headscale/policy.hujson",
        },
    }

    # tagOwners must define the operator/proxy tags, otherwise the operator's
    # v2-API CreateKey call for tag:k8s-operator is rejected with
    # "tag ... is not defined in policy (400)" and it never registers.
    policy = json.dumps(
        {
            "tagOwners": {
                "tag:k8s-operator": [],
                "tag:k8s": ["tag:k8s-operator"],
            },
            "acls": [{"action": "accept", "src": ["*"], "dst": ["*:*"]}],
        },
        indent=2,
    )

    manifest = f"""
apiVersion: v1
kind: ConfigMap
metadata:
  name: {HEADSCALE_NAME}-config
data:
  config.yaml: |
{chr(10).join('    ' + line for line in yaml.dump(config).splitlines())}
  policy.hujson: |
{chr(10).join('    ' + line for line in policy.splitlines())}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {HEADSCALE_NAME}
  labels:
    app: {HEADSCALE_NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {HEADSCALE_NAME}
  template:
    metadata:
      labels:
        app: {HEADSCALE_NAME}
    spec:
      containers:
      - name: headscale
        image: {HEADSCALE_IMAGE}
        command: ["headscale", "serve"]
        ports:
        - containerPort: 8080
        - containerPort: 3478
          protocol: UDP
        volumeMounts:
        - name: config
          mountPath: /etc/headscale/config.yaml
          subPath: config.yaml
        - name: config
          mountPath: /etc/headscale/policy.hujson
          subPath: policy.hujson
        - name: data
          mountPath: /var/lib/headscale
      volumes:
      - name: config
        configMap:
          name: {HEADSCALE_NAME}-config
      - name: data
        emptyDir: {{}}
"""
    kubectl_apply(manifest, namespace)
    wait_for_deployment(HEADSCALE_NAME, namespace)
    return server_url



def create_headscale_oauth_client(namespace: str) -> dict:
    """Create a Headscale user and OAuth client, returning credentials.

    Returns:
        dict with 'client-id' and 'client-secret'.
    """
    # Create a user for the operator
    rc, _, err = headscale_exec(namespace, "headscale", "users", "create", "operator")
    if rc != 0 and "already exists" not in err:
        raise RuntimeError(f"Failed to create user: {err}")

    # Create an OAuth client with the required scopes and tags
    rc, out, err = headscale_exec(
        namespace, "headscale", "oauth-clients", "create",
        "--scope", "devices:core", "--scope", "auth_keys",
        "--tag", "tag:k8s-operator",
        "-o", "json",
    )
    if rc != 0:
        raise RuntimeError(f"Failed to create OAuth client: {err}")

    # Parse JSON output - fields are "id" and "key"
    data = json.loads(out)
    client_id = data.get("id", "")
    client_secret = data.get("key", "")

    if not client_id or not client_secret:
        raise RuntimeError(
            f"Could not parse OAuth client credentials from headscale output: {data}"
        )

    return {"client-id": client_id, "client-secret": client_secret}


def deploy_httpbin(namespace: str):
    """Deploy a simple HTTP server workload."""
    manifest = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {HTTPBIN_NAME}
  labels:
    app: {HTTPBIN_NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {HTTPBIN_NAME}
  template:
    metadata:
      labels:
        app: {HTTPBIN_NAME}
        app.kubernetes.io/name: {HTTPBIN_NAME}
    spec:
      containers:
      - name: httpbin
        image: docker.io/kennethreitz/httpbin:latest
        ports:
        - containerPort: 80
"""
    kubectl_apply(manifest, namespace)
    wait_for_deployment(HTTPBIN_NAME, namespace)


def create_tailscale_lb_service(namespace: str, app_name: str, port: int = 80):
    """Create a LoadBalancer Service with loadBalancerClass: tailscale.

    This is what tailscale-beacon-k8s would create.
    """
    manifest = f"""
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-tailscale
  labels:
    tailscale.com/proxy-class: {DERP_WS_PROXYCLASS}
  annotations:
    tailscale.com/hostname: {app_name}
spec:
  type: LoadBalancer
  loadBalancerClass: tailscale
  selector:
    app.kubernetes.io/name: {app_name}
  ports:
  - port: {port}
    targetPort: {port}
"""
    kubectl_apply(manifest, namespace)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(scope="module")
async def charm_path(ops_test: OpsTest):
    """Build the charm for testing."""
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)
    return await ops_test.build_charm(".")


@pytest.fixture(scope="module")
def headscale_url(ops_test):
    """Deploy Headscale (HTTP + embedded DERP) and return its in-cluster URL."""
    namespace = ops_test.model.name
    return deploy_headscale(namespace)


@pytest.fixture(scope="module")
def headscale_credentials(ops_test, headscale_url):
    """Create OAuth credentials on Headscale."""
    return create_headscale_oauth_client(ops_test.model.name)


@pytest.fixture(scope="module", autouse=True)
def cleanup_tailscale_lb_services(ops_test):
    """Remove `loadBalancerClass: tailscale` Services before the model is torn down.

    The upstream operator adds a `tailscale.com/finalizer` to every such Service.
    If the model/operator is destroyed while one still exists, the operator is
    removed before it clears the finalizer, so the Service (and therefore its
    namespace, and therefore the whole model) gets stuck deleting forever.

    On teardown we first delete the Services while the operator is still running
    so it can clear the finalizers cleanly, then strip any leftover finalizer as
    a safety net so model destruction can never wedge.
    """
    yield
    namespace = ops_test.model.name
    # Names of the tailscale LoadBalancer Services this module may have created.
    rc, out, _ = kubectl(
        "get", "svc",
        "-o", 'jsonpath={range .items[?(@.spec.loadBalancerClass=="tailscale")]}'
        '{.metadata.name}{"\\n"}{end}',
        namespace=namespace,
    )
    services = [s for s in out.split("\n") if s.strip()] if rc == 0 else []
    for svc in services:
        # Delete while the operator is alive so it clears the finalizer properly.
        kubectl("delete", "svc", svc, "--ignore-not-found", "--timeout=30s",
                namespace=namespace)
        # Safety net: strip the finalizer if the operator is already gone.
        kubectl("patch", "svc", svc, "--type=json",
                "-p", '[{"op":"remove","path":"/metadata/finalizers"}]',
                namespace=namespace)


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.abort_on_fail
async def test_deploy_with_headscale_credentials(
    ops_test: OpsTest, charm_path, headscale_url, headscale_credentials
):
    """Deploy tailscale-k8s with real Headscale credentials and verify it goes active."""
    namespace = ops_test.model.name

    # Deploy the charm
    await ops_test.model.deploy(
        charm_path,
        resources=RESOURCES,
        application_name=APP_NAME,
        trust=True,
    )

    # Wait for blocked (no credentials yet)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="blocked", timeout=300,
    )

    # Create Juju secret with Headscale OAuth credentials
    secret_id = await ops_test.model.add_secret(
        name="headscale-oauth-creds",
        data_args=[
            f"client-id={headscale_credentials['client-id']}",
            f"client-secret={headscale_credentials['client-secret']}",
        ],
    )
    await ops_test.juju(
        "grant-secret", "headscale-oauth-creds", APP_NAME, "--model", namespace,
    )

    # Configure the charm with the (plain-HTTP) Headscale login server + creds.
    app = ops_test.model.applications[APP_NAME]
    await app.set_config({
        "credentials": secret_id,
        "login-server": headscale_url,
    })

    # The operator should authenticate over HTTP, register, and the charm should
    # reach active.
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=300, raise_on_error=False,
    )

    unit = app.units[0]
    assert "No credentials" not in (unit.workload_status_message or ""), (
        f"Charm still blocked for credentials: {unit.workload_status_message}"
    )
    assert unit.workload_status == "active", (
        f"Unexpected status {unit.workload_status}: {unit.workload_status_message}"
    )


@pytest.mark.abort_on_fail
async def test_operator_registered_on_headscale(ops_test: OpsTest):
    """Verify the operator device registered itself on Headscale."""
    namespace = ops_test.model.name

    # Refresh status
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], timeout=30, raise_on_error=False, raise_on_blocked=False,
    )

    # Skip if the operator didn't reach active (upstream compatibility issue)
    app = ops_test.model.applications[APP_NAME]
    unit = app.units[0]
    if unit.workload_status != "active":
        pytest.skip(
            f"Operator not active ({unit.workload_status}: {unit.workload_status_message}). "
            "Headscale OAuth compatibility may require a newer operator or Headscale version."
        )

    # Give the operator a moment to register
    time.sleep(10)

    rc, out, err = headscale_exec(namespace, "headscale", "nodes", "list", "-o", "json")
    assert rc == 0, f"Failed to list nodes: {err}"

    nodes = json.loads(out)
    # The operator should have registered with a hostname containing 'tailscale-operator'
    operator_nodes = [
        n for n in nodes
        if "tailscale-operator" in n.get("givenName", "").lower()
        or "tailscale-operator" in n.get("name", "").lower()
    ]
    assert len(operator_nodes) > 0, (
        f"Operator node not found on Headscale. Nodes: {[n.get('givenName', n.get('name')) for n in nodes]}"
    )


@pytest.mark.abort_on_fail
async def test_workload_exposed_via_loadbalancer(ops_test: OpsTest):
    """Create a LoadBalancer Service and verify the operator creates a proxy for it.

    This simulates what tailscale-beacon-k8s would do: creating a Service with
    loadBalancerClass: tailscale.
    """
    namespace = ops_test.model.name

    # Skip if the operator didn't reach active
    app = ops_test.model.applications[APP_NAME]
    unit = app.units[0]
    if unit.workload_status != "active":
        pytest.skip("Operator not active — cannot test workload exposure")

    # Deploy a simple HTTP workload
    deploy_httpbin(namespace)

    # Create the DERP-over-HTTP ProxyClass so the proxy can reach the non-TLS
    # embedded DERP, then create a LoadBalancer Service (simulating
    # tailscale-beacon-k8s) that selects it.
    create_derp_ws_proxyclass()
    create_tailscale_lb_service(namespace, HTTPBIN_NAME, port=80)

    # Wait for the operator to reconcile the Service and create a proxy
    # The proxy is a StatefulSet created by the operator
    deadline = time.time() + 120
    proxy_ready = False
    while time.time() < deadline:
        rc, out, _ = kubectl(
            "get", "statefulset", "-l", "tailscale.com/parent-resource-type=svc",
            "-o", "jsonpath={.items[*].metadata.name}",
            namespace=namespace,
        )
        if rc == 0 and out.strip():
            proxy_ready = True
            logger.info("Proxy StatefulSet found: %s", out.strip())
            break
        time.sleep(5)

    assert proxy_ready, "Operator did not create a proxy StatefulSet for the LoadBalancer Service"


@pytest.mark.abort_on_fail
async def test_workload_gets_tailnet_address(ops_test: OpsTest):
    """Verify the LoadBalancer Service gets a tailnet address assigned."""
    namespace = ops_test.model.name

    # Skip if the operator didn't reach active
    app = ops_test.model.applications[APP_NAME]
    unit = app.units[0]
    if unit.workload_status != "active":
        pytest.skip("Operator not active — cannot test tailnet address assignment")

    deadline = time.time() + 120
    address = ""
    while time.time() < deadline:
        rc, out, _ = kubectl(
            "get", "svc", f"{HTTPBIN_NAME}-tailscale",
            "-o", "jsonpath={.status.loadBalancer.ingress[0].hostname}",
            namespace=namespace,
        )
        if rc == 0 and out.strip():
            address = out.strip()
            break
        # Also check for IP
        rc, out, _ = kubectl(
            "get", "svc", f"{HTTPBIN_NAME}-tailscale",
            "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}",
            namespace=namespace,
        )
        if rc == 0 and out.strip():
            address = out.strip()
            break
        time.sleep(5)

    assert address, (
        "LoadBalancer Service did not receive a tailnet address within timeout"
    )
    logger.info("Workload tailnet address: %s", address)


def create_headscale_preauthkey(namespace: str) -> str:
    """Create a pre-auth key for the 'operator' user, returning the key.

    Returns an empty string if the user or key could not be created/parsed.
    `preauthkeys create` wants the numeric user ID (not name), so resolve it
    from the users list first.
    """
    rc, users_out, _ = headscale_exec(namespace, "headscale", "users", "list", "-o", "json")
    if rc != 0:
        return ""
    user_id = ""
    for u in json.loads(users_out):
        if u.get("name") == "operator" or u.get("display_name") == "operator":
            user_id = str(u.get("id", ""))
            break
    if not user_id:
        return ""

    rc, out, _ = headscale_exec(
        namespace, "headscale", "preauthkeys", "create", "--user", user_id, "-o", "json",
    )
    if rc != 0:
        return ""

    try:
        key = json.loads(out).get("key", "")
        if key:
            return key
    except (json.JSONDecodeError, AttributeError):
        pass
    for line in out.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(stripped) > 20:
            return stripped
    return ""


def get_proxy_tailnet_ip(namespace: str, hostname_substr: str) -> str:
    """Return the tailnet IPv4 of the proxy node whose name matches hostname_substr.

    The LoadBalancer ingress often exposes a MagicDNS name the userspace client
    can't resolve, so for connectivity we use the proxy's actual 100.x address
    from Headscale's node list.
    """
    rc, out, _ = headscale_exec(namespace, "headscale", "nodes", "list", "-o", "json")
    if rc != 0:
        return ""
    for node in json.loads(out):
        name = (node.get("givenName") or node.get("name") or "").lower()
        if hostname_substr.lower() not in name:
            continue
        for ip in node.get("ipAddresses") or node.get("ip_addresses") or []:
            if ip.startswith("100."):
                return ip
    return ""


async def test_tailnet_client_can_reach_workload(ops_test: OpsTest, headscale_credentials, headscale_url):
    """Join a tailscale client to the same tailnet and verify it can reach the workload.

    This proves that "other charms" (or any tailnet member) can communicate
    with workloads exposed through the operator.
    """
    namespace = ops_test.model.name

    # Skip if the operator didn't reach active
    app = ops_test.model.applications[APP_NAME]
    unit = app.units[0]
    if unit.workload_status != "active":
        pytest.skip("Operator not active — cannot test tailnet connectivity")

    auth_key = create_headscale_preauthkey(namespace)
    if not auth_key:
        pytest.skip("Could not create/parse a Headscale pre-auth key")

    # Deploy a tailscale client pod that joins the tailnet. It reaches the
    # non-TLS embedded DERP the same way proxies do: plain-HTTP websocket DERP.
    client_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: ts-client
spec:
  containers:
  - name: tailscale
    image: docker.io/tailscale/tailscale:v1.98
    command: ["tailscaled", "--tun=userspace-networking"]
    securityContext:
      capabilities:
        add: ["NET_ADMIN"]
    env:
    - name: TS_AUTHKEY
      value: "{auth_key}"
    - name: TS_LOGIN_SERVER
      value: "{headscale_url}"
    - name: TS_USERSPACE
      value: "true"
    - name: TS_DEBUG_DERP_WS_CLIENT
      value: "true"
    - name: TS_DEBUG_USE_DERP_HTTP
      value: "true"
"""
    kubectl_apply(client_manifest, namespace)

    # Wait for the client pod to be running
    deadline = time.time() + 60
    while time.time() < deadline:
        rc, out, _ = kubectl(
            "get", "pod", "ts-client", "-o", "jsonpath={.status.phase}",
            namespace=namespace,
        )
        if rc == 0 and out.strip() == "Running":
            break
        time.sleep(5)

    # Give tailscale time to connect
    time.sleep(15)

    # Resolve the workload proxy's actual tailnet IP from Headscale (the LB
    # ingress exposes a MagicDNS name the userspace client can't resolve).
    workload_ip = ""
    deadline = time.time() + 60
    while time.time() < deadline:
        workload_ip = get_proxy_tailnet_ip(namespace, HTTPBIN_NAME)
        if workload_ip:
            break
        time.sleep(5)
    assert workload_ip, "Could not resolve the workload proxy's tailnet IP from Headscale"
    logger.info("Workload proxy tailnet IP: %s", workload_ip)

    # Reach the workload from the client pod over the tailnet, with retries to
    # allow the data path (WireGuard/DERP) to establish.
    last_err = ""
    reached = False
    deadline = time.time() + 90
    while time.time() < deadline:
        result = subprocess.run(
            ["kubectl", "exec", "-n", namespace, "ts-client", "--",
             "wget", "-q", "-O", "-", "--timeout=10", f"http://{workload_ip}/get"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and ("headers" in result.stdout or "origin" in result.stdout):
            reached = True
            logger.info("Workload reachable from tailnet client via %s", workload_ip)
            break
        last_err = result.stderr.strip()
        time.sleep(5)

    assert reached, (
        f"Could not reach workload at {workload_ip} from the tailnet client "
        f"within timeout. Last error: {last_err}"
    )
