#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the tailscale-k8s charm."""

import logging
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from lightkube import ApiError, Client
from lightkube.generic_resource import create_global_resource
from lightkube.resources.core_v1 import ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    "tailscale-operator-image": METADATA["resources"]["tailscale-operator-image"][
        "upstream-source"
    ],
}

IngressClass = create_global_resource(
    group="networking.k8s.io",
    version="v1",
    kind="IngressClass",
    plural="ingressclasses",
)


@pytest.fixture(scope="module")
async def charm_path(ops_test: OpsTest):
    """Build the charm for testing."""
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)
    return await ops_test.build_charm(".")


# =============================================================================
# Deployment and Initial Status
# =============================================================================


@pytest.mark.abort_on_fail
async def test_build_and_deploy_blocked_no_credentials(ops_test: OpsTest, charm_path):
    """Deploy the charm without credentials - should go to blocked status."""
    await ops_test.model.deploy(
        charm_path,
        resources=RESOURCES,
        application_name=APP_NAME,
        trust=True,
    )
    # The charm should block because no credentials are configured
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=300,
    )

    app = ops_test.model.applications[APP_NAME]
    unit = app.units[0]
    assert unit.workload_status == "blocked"
    assert "No credentials" in unit.workload_status_message


# =============================================================================
# Kubernetes Resource Verification
# =============================================================================


@pytest.mark.abort_on_fail
async def test_service_account_created(ops_test: OpsTest):
    """Verify ServiceAccount 'proxies' is created with correct labels."""
    namespace = ops_test.model.name
    lc = Client()

    sa = lc.get(ServiceAccount, name="proxies", namespace=namespace)
    assert sa is not None
    assert sa.metadata.labels.get("kubernetes-resource-handler-scope") == "operator-resources"
    assert sa.metadata.labels.get("app.kubernetes.io/instance") == (
        f"{namespace}-{APP_NAME}"
    )


@pytest.mark.abort_on_fail
async def test_role_created_with_correct_rules(ops_test: OpsTest):
    """Verify Role 'proxies' has the correct RBAC rules for proxy pods."""
    namespace = ops_test.model.name
    lc = Client()

    role = lc.get(Role, name="proxies", namespace=namespace)
    assert role is not None
    assert role.metadata.labels.get("kubernetes-resource-handler-scope") == "operator-resources"

    # Verify secrets rule
    secrets_rule = None
    events_rule = None
    for rule in role.rules:
        if "secrets" in rule.resources:
            secrets_rule = rule
        if "events" in rule.resources:
            events_rule = rule

    assert secrets_rule is not None, "No rule for 'secrets' found"
    assert set(secrets_rule.verbs) == {
        "create", "get", "list", "watch", "update", "patch", "delete"
    }
    assert "" in secrets_rule.apiGroups  # core API group

    assert events_rule is not None, "No rule for 'events' found"
    assert "create" in events_rule.verbs
    assert "patch" in events_rule.verbs
    assert "" in events_rule.apiGroups  # core API group


@pytest.mark.abort_on_fail
async def test_rolebinding_binds_correct_sa(ops_test: OpsTest):
    """Verify RoleBinding 'proxies' references the correct SA and Role."""
    namespace = ops_test.model.name
    lc = Client()

    rb = lc.get(RoleBinding, name="proxies", namespace=namespace)
    assert rb is not None
    assert rb.metadata.labels.get("kubernetes-resource-handler-scope") == "operator-resources"

    # Verify role reference
    assert rb.roleRef.name == "proxies"
    assert rb.roleRef.kind == "Role"
    assert rb.roleRef.apiGroup == "rbac.authorization.k8s.io"

    # Verify subject references the proxies SA in the same namespace
    assert len(rb.subjects) == 1
    subject = rb.subjects[0]
    assert subject.kind == "ServiceAccount"
    assert subject.name == "proxies"
    assert subject.namespace == namespace


@pytest.mark.abort_on_fail
async def test_ingressclass_created_with_correct_controller(ops_test: OpsTest):
    """Verify IngressClass 'tailscale' registers the correct controller."""
    lc = Client()
    namespace = ops_test.model.name

    ic = lc.get(IngressClass, name="tailscale")
    assert ic is not None

    # For generic resources, metadata may be dict or ObjectMeta
    metadata = ic.metadata
    if isinstance(metadata, dict):
        labels = metadata.get("labels") or {}
    else:
        labels = metadata.labels or {}
    assert labels.get("kubernetes-resource-handler-scope") == "operator-resources"
    assert labels.get("app.kubernetes.io/instance") == f"{namespace}-{APP_NAME}"

    # Check controller
    spec = ic.spec if isinstance(ic.spec, dict) else ic.to_dict().get("spec", {})
    assert spec.get("controller") == "tailscale.com/ts-ingress"


# =============================================================================
# Scaling Enforcement
# =============================================================================


@pytest.mark.abort_on_fail
async def test_scaling_beyond_one_blocks_leader(ops_test: OpsTest):
    """Scaling beyond 1 replica should block the leader unit."""
    app = ops_test.model.applications[APP_NAME]
    await app.scale(2)

    # Wait for the units to settle
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        timeout=120,
        raise_on_error=False,
    )

    # Check that the leader reports the scaling error
    leader_found_blocking = False
    for unit in app.units:
        if "multiple replicas" in (unit.workload_status_message or ""):
            leader_found_blocking = True
            break
    assert leader_found_blocking, "No unit reported the 'multiple replicas' block status"


@pytest.mark.abort_on_fail
async def test_non_leader_standby_while_scaled(ops_test: OpsTest):
    """Non-leader units should report active standby regardless of scaling."""
    app = ops_test.model.applications[APP_NAME]

    # Find the non-leader unit
    for unit in app.units:
        if unit.workload_status_message == "Standby (non-leader)":
            assert unit.workload_status == "active"
            break
    else:
        pytest.fail("No non-leader unit found with 'Standby (non-leader)' status")


@pytest.mark.abort_on_fail
async def test_scale_back_to_one_unblocks(ops_test: OpsTest):
    """Scaling back to 1 should remove the scaling block."""
    app = ops_test.model.applications[APP_NAME]
    await app.scale(1)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=120,
    )
    unit = app.units[0]
    assert "multiple replicas" not in (unit.workload_status_message or "")
    # Should be back to the "No credentials" block
    assert "No credentials" in unit.workload_status_message


# =============================================================================
# Credential Configuration
# =============================================================================


@pytest.mark.abort_on_fail
async def test_add_credentials_transitions_past_blocked(ops_test: OpsTest):
    """Adding credentials should move the charm past the 'No credentials' block.

    With dummy credentials the operator binary crash-loops on auth (401), so the
    charm settles into either 'active' (sampled while the Pebble service is in a
    post-restart running window) or 'waiting' (sampled during backoff). Both mean
    the credentials were accepted and the operator was configured; asserting the
    exact transient would be racy, so we only require it left the blocked state.
    """
    # Create a secret with test credentials
    secret_id = await ops_test.model.add_secret(
        name="tailscale-integ-creds",
        data_args=["client-id=test-client-id", "client-secret=test-client-secret"],
    )

    app = ops_test.model.applications[APP_NAME]
    await ops_test.juju(
        "grant-secret", "tailscale-integ-creds", APP_NAME, "--model", ops_test.model.name
    )
    await app.set_config({"credentials": secret_id})

    # Should leave the blocked state (operator configured, even if it can't auth).
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        timeout=120,
        raise_on_error=False,
        raise_on_blocked=False,
    )

    unit = app.units[0]
    assert unit.workload_status in ("active", "waiting"), (
        f"Unexpected status {unit.workload_status}: {unit.workload_status_message}"
    )
    assert "No credentials" not in (unit.workload_status_message or "")


@pytest.mark.abort_on_fail
async def test_credentials_pushed_to_container(ops_test: OpsTest):
    """Verify that credential files are written to the container filesystem."""
    namespace = ops_test.model.name
    pod_name = f"{APP_NAME}-0"

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--", "cat", "/oauth/client_id"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"kubectl exec failed: {result.stderr}"
    assert result.stdout.strip() == "test-client-id"

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--", "cat", "/oauth/client_secret"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"kubectl exec failed: {result.stderr}"
    assert result.stdout.strip() == "test-client-secret"


@pytest.mark.abort_on_fail
async def test_pebble_layer_environment(ops_test: OpsTest):
    """Verify the Pebble layer sets correct environment variables."""
    namespace = ops_test.model.name
    pod_name = f"{APP_NAME}-0"

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--",
         "/charm/bin/pebble", "plan"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"pebble plan failed: {result.stderr}"

    plan = yaml.safe_load(result.stdout)
    svc = plan["services"]["tailscale-operator"]

    assert svc["command"] == "/usr/local/bin/operator"
    env = svc["environment"]
    assert env["CLIENT_ID_FILE"] == "/oauth/client_id"
    assert env["CLIENT_SECRET_FILE"] == "/oauth/client_secret"
    assert env["OPERATOR_INITIAL_TAGS"] == "tag:k8s-operator"
    assert env["PROXY_TAGS"] == "tag:k8s"
    assert env["OPERATOR_NAMESPACE"] == namespace
    assert env["APISERVER_PROXY"] == "false"
    assert env["PROXY_FIREWALL_MODE"] == "auto"
    # No login server when using default (Tailscale SaaS)
    assert "OPERATOR_LOGIN_SERVER" not in env


# =============================================================================
# Configuration Changes
# =============================================================================


@pytest.mark.abort_on_fail
async def test_custom_tags_config(ops_test: OpsTest):
    """Custom operator-tags and proxy-tags should be reflected in the container."""
    namespace = ops_test.model.name
    pod_name = f"{APP_NAME}-0"

    app = ops_test.model.applications[APP_NAME]
    await app.set_config({
        "operator-tags": "tag:my-operator,tag:extra",
        "proxy-tags": "tag:my-proxy",
    })

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        timeout=60,
        raise_on_error=False,
    )

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--",
         "/charm/bin/pebble", "plan"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"pebble plan failed: {result.stderr}"
    plan = yaml.safe_load(result.stdout)
    env = plan["services"]["tailscale-operator"]["environment"]
    assert env["OPERATOR_INITIAL_TAGS"] == "tag:my-operator,tag:extra"
    assert env["PROXY_TAGS"] == "tag:my-proxy"


@pytest.mark.abort_on_fail
async def test_custom_login_server_config(ops_test: OpsTest):
    """Setting login-server should add OPERATOR_LOGIN_SERVER env var."""
    namespace = ops_test.model.name
    pod_name = f"{APP_NAME}-0"

    app = ops_test.model.applications[APP_NAME]
    await app.set_config({"login-server": "https://headscale.example.com"})

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        timeout=60,
        raise_on_error=False,
    )

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--",
         "/charm/bin/pebble", "plan"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"pebble plan failed: {result.stderr}"
    plan = yaml.safe_load(result.stdout)
    env = plan["services"]["tailscale-operator"]["environment"]
    assert env["OPERATOR_LOGIN_SERVER"] == "https://headscale.example.com"


@pytest.mark.abort_on_fail
async def test_clear_login_server_removes_env(ops_test: OpsTest):
    """Clearing login-server should remove OPERATOR_LOGIN_SERVER env var."""
    namespace = ops_test.model.name
    pod_name = f"{APP_NAME}-0"

    app = ops_test.model.applications[APP_NAME]
    await app.set_config({"login-server": ""})

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        timeout=60,
        raise_on_error=False,
    )

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--",
         "/charm/bin/pebble", "plan"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"pebble plan failed: {result.stderr}"
    plan = yaml.safe_load(result.stdout)
    env = plan["services"]["tailscale-operator"]["environment"]
    assert "OPERATOR_LOGIN_SERVER" not in env


@pytest.mark.abort_on_fail
async def test_reset_tags_to_defaults(ops_test: OpsTest):
    """Resetting tags config to defaults should revert env vars."""
    namespace = ops_test.model.name
    pod_name = f"{APP_NAME}-0"

    app = ops_test.model.applications[APP_NAME]
    await app.set_config({
        "operator-tags": "tag:k8s-operator",
        "proxy-tags": "tag:k8s",
    })

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        timeout=60,
        raise_on_error=False,
    )

    result = subprocess.run(
        ["kubectl", "exec", "-n", namespace, pod_name,
         "-c", "tailscale-operator", "--",
         "/charm/bin/pebble", "plan"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"pebble plan failed: {result.stderr}"
    plan = yaml.safe_load(result.stdout)
    env = plan["services"]["tailscale-operator"]["environment"]
    assert env["OPERATOR_INITIAL_TAGS"] == "tag:k8s-operator"
    assert env["PROXY_TAGS"] == "tag:k8s"


# =============================================================================
# Credential Removal
# =============================================================================


@pytest.mark.abort_on_fail
async def test_remove_credentials_blocks_charm(ops_test: OpsTest):
    """Removing credentials should return the charm to blocked status."""
    app = ops_test.model.applications[APP_NAME]
    # Clear the credentials config
    await app.reset_config(["credentials"])

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=120,
    )

    unit = app.units[0]
    assert unit.workload_status == "blocked"
    assert "No credentials" in unit.workload_status_message


# =============================================================================
# Removal and Cleanup
# =============================================================================


async def test_removal_cleans_up_service_account(ops_test: OpsTest):
    """Verify ServiceAccount 'proxies' is deleted on charm removal."""
    namespace = ops_test.model.name
    await ops_test.model.remove_application(APP_NAME, block_until_done=True)

    lc = Client()
    try:
        lc.get(ServiceAccount, name="proxies", namespace=namespace)
        pytest.fail("ServiceAccount 'proxies' still exists after removal")
    except ApiError as e:
        assert e.status.code == 404


async def test_removal_cleans_up_role(ops_test: OpsTest):
    """Verify Role 'proxies' is deleted on charm removal."""
    namespace = ops_test.model.name
    lc = Client()
    try:
        lc.get(Role, name="proxies", namespace=namespace)
        pytest.fail("Role 'proxies' still exists after removal")
    except ApiError as e:
        assert e.status.code == 404


async def test_removal_cleans_up_rolebinding(ops_test: OpsTest):
    """Verify RoleBinding 'proxies' is deleted on charm removal."""
    namespace = ops_test.model.name
    lc = Client()
    try:
        lc.get(RoleBinding, name="proxies", namespace=namespace)
        pytest.fail("RoleBinding 'proxies' still exists after removal")
    except ApiError as e:
        assert e.status.code == 404


async def test_removal_cleans_up_ingressclass(ops_test: OpsTest):
    """Verify IngressClass 'tailscale' is deleted on charm removal."""
    lc = Client()
    try:
        lc.get(IngressClass, name="tailscale")
        pytest.fail("IngressClass 'tailscale' still exists after removal")
    except ApiError as e:
        assert e.status.code == 404


# =============================================================================
# Placeholder Tests — Require tailscale-config Charm (Not Yet Implemented)
# =============================================================================


@pytest.mark.skip(reason="Requires tailscale-config charm (not yet implemented)")
async def test_tailscale_config_relation_provides_credentials(ops_test: OpsTest):
    """tailscale-config relation should provide OAuth credentials automatically.

    When related to tailscale-config, the charm should receive a child OAuth
    client ID and secret via the tailscale-credentials relation, eliminating
    the need for manual credential configuration.
    """


@pytest.mark.skip(reason="Requires tailscale-config charm (not yet implemented)")
async def test_credential_conflict_blocks_when_both_present(ops_test: OpsTest):
    """Both manual credentials and tailscale-config relation should block the charm.

    If both the 'credentials' config option AND the tailscale-credentials relation
    are present, the charm MUST block rather than picking a winner.
    """


@pytest.mark.skip(reason="Requires tailscale-config charm (not yet implemented)")
async def test_credential_revocation_on_relation_removal(ops_test: OpsTest):
    """Removing the tailscale-config relation should revoke the child credential.

    When the tailscale-credentials relation is broken, tailscale-config should
    revoke the child OAuth client it minted for this downstream.
    """


@pytest.mark.skip(reason="Requires tailscale-config charm (not yet implemented)")
async def test_cross_model_relation_with_tailscale_config(ops_test: OpsTest):
    """tailscale-config can provide credentials across models via CMR.

    tailscale-config may live in a different model. The credential distribution
    must work identically over a cross-model relation (offer/consume).
    """


@pytest.mark.skip(reason="Requires tailscale-config charm (not yet implemented)")
async def test_headscale_backend_login_server_from_relation(ops_test: OpsTest):
    """Headscale login-server URL should be received via tailscale-config relation.

    When tailscale-config is configured with backend=headscale, the login-server
    URL and pre-auth key should be passed to tailscale-k8s via relation data.
    The operator should use OPERATOR_LOGIN_SERVER to point at the Headscale instance.
    """


# =============================================================================
# Placeholder Tests — Require tailscale-beacon-k8s Charm (Not Yet Implemented)
# =============================================================================


@pytest.mark.skip(reason="Requires tailscale-beacon-k8s charm (not yet implemented)")
async def test_beacon_loadbalancer_service_picked_up_by_operator(ops_test: OpsTest):
    """Operator should reconcile LoadBalancer Services created by beacon charm.

    When tailscale-beacon-k8s creates a LoadBalancer Service with
    loadBalancerClass: tailscale, the operator (managed by this charm) should
    detect it, create a proxy StatefulSet, and register the app on the tailnet.
    """


@pytest.mark.skip(reason="Requires tailscale-beacon-k8s charm (not yet implemented)")
async def test_beacon_service_gets_tailnet_hostname(ops_test: OpsTest):
    """The beacon's LoadBalancer Service should eventually get a tailnet hostname.

    Once the operator reconciles the Service, .status.loadBalancer.ingress
    should be populated with the MagicDNS hostname of the exposed workload.
    """


@pytest.mark.skip(reason="Requires tailscale-beacon-k8s and real tailnet credentials")
async def test_end_to_end_workload_reachable_on_tailnet(ops_test: OpsTest):
    """Full end-to-end: a workload exposed via beacon should be reachable on the tailnet.

    Deploy an HTTP workload, relate it to tailscale-beacon-k8s, and verify
    the workload is reachable from another tailnet member via its MagicDNS name.
    """


# =============================================================================
# Placeholder Tests — Require Real Tailscale/Headscale Credentials
# =============================================================================


@pytest.mark.skip(reason="Requires real Tailscale OAuth credentials")
async def test_operator_active_with_real_credentials(ops_test: OpsTest):
    """With valid credentials, the operator binary should start and the charm go active.

    This test requires actual Tailscale OAuth credentials that allow the operator
    to authenticate and register its device on the tailnet.
    """


@pytest.mark.skip(reason="Requires real Tailscale OAuth credentials")
async def test_operator_installs_crds(ops_test: OpsTest):
    """The operator should install its CRDs on startup.

    When running with valid credentials, the operator creates:
    connectors, proxyclasses, proxygroups, dnsconfigs, tailnets, recorders,
    proxygrouppolicies CRDs. (Note: CRDs are now installed by the charm itself
    prior to starting the operator.)
    """


@pytest.mark.skip(reason="Requires real Tailscale OAuth credentials and device approval enabled")
async def test_needs_machine_auth_surfaced_as_blocked(ops_test: OpsTest):
    """NeedsMachineAuth should be surfaced as BlockedStatus.

    When a non-pre-authorized key is used on a tailnet with device approval
    enabled, the operator device lands in NeedsMachineAuth. The charm should
    detect this and report BlockedStatus directing the admin to approve.
    """


@pytest.mark.skip(reason="Requires real Tailscale OAuth credentials")
async def test_tag_ownership_check_blocks_on_missing_operator_tag(ops_test: OpsTest):
    """Charm should block if credential does not carry the configured operator tags.

    tailscale-k8s performs a check: operator-tags must be a subset of the
    credential's carried tags. If a configured operator tag is not carried,
    the charm blocks with a message naming the missing tag(s).
    """


@pytest.mark.skip(reason="Requires real Tailscale OAuth credentials")
async def test_proxy_tag_failure_detected_at_runtime(ops_test: OpsTest):
    """Proxy tag ownership failure should be detected via Service status.

    If the operator tag does not own the proxy tag in tagOwners, the operator's
    CreateKey for proxy pods fails. This manifests as the exposed Service never
    getting a LoadBalancer ingress address. The charm should eventually surface
    this as a warning or blocked status.
    """


# =============================================================================
# Placeholder Tests — Second Operator Detection
# =============================================================================


@pytest.mark.skip(reason="Requires deploying a second tailscale-k8s instance on same cluster")
async def test_second_operator_detected_and_blocked(ops_test: OpsTest):
    """Deploying a second tailscale-k8s on the same cluster should be detected.

    The second instance should find the IngressClass already exists (created by
    the first instance) and enter BlockedStatus with 'Another Tailscale operator
    detected on this cluster'.
    """
