"""Fixtures for Tailscale solution tests."""

import json
import os
import subprocess

import jubilant
import pytest

from integration.tailscale.helpers import (
    credential_revoked,
    get_credential_ids,
    remove_tailnet_devices,
    wait_proxy_removed,
)

pytest_plugins = [
    "integration.tailscale.steps.credential_steps",
    "integration.tailscale.steps.common_steps",
    "integration.tailscale.steps.topology_steps",
]


@pytest.fixture(scope="module")
def tailnet():
    """Require credentials and an already enrolled test client."""
    for name in ("TAILSCALE_CLIENT_ID", "TAILSCALE_CLIENT_SECRET"):
        if not os.environ.get(name):
            raise pytest.UsageError(f"{name} is required for Tailscale solution tests")
    result = subprocess.run(
        ["tailscale", "status", "--json"], capture_output=True, text=True, check=True, timeout=30
    )
    status = json.loads(result.stdout)
    if status.get("BackendState") != "Running" or not status.get("MagicDNSSuffix"):
        raise pytest.UsageError("The test client must be enrolled in a tailnet with MagicDNS")
    return status["MagicDNSSuffix"]


@pytest.fixture
def tailscale_system_juju(request, tailnet):
    """Use a fresh operator without relying on credential replacement or hidden restarts."""
    with jubilant.temp_model(
        controller=request.config.getoption("--juju-controller"),
        cloud=request.config.getoption("--juju-cloud"),
    ) as juju:
        namespace = juju.status().model.name
        yield juju
    subprocess.run(
        ["kubectl", "wait", "--for=delete", f"namespace/{namespace}",
         "ingressclass/tailscale", "--timeout=300s"],
        check=True, capture_output=True, text=True, timeout=310,
    )


@pytest.fixture(scope="module")
def second_bookinfo_juju(juju_factory):
    """Create another workload model for cross-model ingress scenarios."""
    yield juju_factory.get_juju(suffix="bookinfo-b")


@pytest.fixture(scope="module")
def credentials_juju(juju_factory):
    """Create the separate credential-provider model for topology scenarios."""
    yield juju_factory.get_juju(suffix="credentials")


@pytest.fixture(scope="module")
def terraform_state(tmp_path_factory):
    """Keep Terraform state for module-scoped deployments."""
    return tmp_path_factory.mktemp("tailscale")


@pytest.fixture
def credential_info(tailscale_system_juju, request):
    """Remove all ingress before revoking credentials and deleting run-owned devices."""
    namespace = tailscale_system_juju.status().model.name
    info = {
        "provider": None, "remote": "tailscale-config", "related": False, "keys": set(),
        "ingresses": [], "hostnames": {f"tailscale-operator-{namespace}"},
    }
    yield info
    errors = []
    for workload, app in info["ingresses"]:
        try:
            if workload.status().apps[app].relations.get("ingress"):
                workload.remove_relation(f"{app}:ingress", "tailscale-beacon-k8s:ingress")
            wait_proxy_removed(tailscale_system_juju, workload, app)
        except (jubilant.CLIError, jubilant.WaitError, subprocess.SubprocessError, TimeoutError) as exc:
            exc.add_note(f"Ingress cleanup failed for {workload.model}/{app}")
            errors.append(exc)
    if errors:
        request.session.shouldstop = "Ingress cleanup failed; resolve remaining resources before rerunning"
        raise ExceptionGroup(
            "Ingress cleanup failed; credential revocation and device deletion were not attempted",
            errors,
        )
    if info["related"]:
        provider = info["provider"]
        keys = get_credential_ids(provider)
        tailscale_system_juju.remove_relation(
            "tailscale-k8s:tailscale-credentials", f"{info['remote']}:tailscale-credentials"
        )
        provider.wait(
            lambda _: not get_credential_ids(provider) and all(credential_revoked(k) for k in keys),
            timeout=300, error=jubilant.any_error,
        )
    remove_tailnet_devices(info["hostnames"])


@pytest.fixture
def ingress_relations(credential_info):
    """Record the ingress relations that must be removed before credential cleanup."""
    return credential_info["ingresses"]


@pytest.fixture
def tailnet_devices(credential_info):
    """Record exact device hostnames for the scenario's ordered cleanup."""
    return credential_info["hostnames"]


@pytest.fixture
def juju_run_output():
    """Store request results and published URLs for the scenario."""
    return {}


@pytest.fixture
def bookinfo_config():
    """Keep all productpage applications when reapplying Terraform for scaling."""
    return {"productpage": {}}


@pytest.fixture(scope="module")
def root_secrets():
    """Reuse each provider model's root secret across scenarios."""
    return {}
