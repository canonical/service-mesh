"""Deployment and request helpers for Tailscale solution tests."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

import jubilant

from integration.helpers import TFManager, curl_from_host


def terraform_environment(juju: jubilant.Juju) -> dict[str, str]:
    """Target the model's controller and UUID using the logged-in Juju CLI account."""
    assert juju.model is not None
    models = json.loads(juju.cli("show-model", juju.model, "--format=json", include_model=False))
    assert len(models) == 1, "Expected exactly one model"
    model = next(iter(models.values()))
    provider_credentials = {
        "JUJU_CONTROLLER_ADDRESSES", "JUJU_USERNAME", "JUJU_PASSWORD", "JUJU_CA_CERT",
        "JUJU_CLIENT_ID", "JUJU_CLIENT_SECRET",
    }
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("TF_VAR_") and key not in provider_credentials
    }
    env.update({
        "JUJU_CONTROLLER": model["controller-name"],
        "JUJU_MODEL": f"{model['controller-name']}:{model['name']}",
        "TF_VAR_model_uuid": model["model-uuid"],
    })
    return env


def deploy_charm(
    juju: jubilant.Juju, charm: str, state_dir: Path, config: dict | None = None
) -> None:
    """Deploy a Tailscale charm using its solution Terraform root."""
    assert juju.model is not None
    roots = {
        "tailscale-k8s": "operator",
        "tailscale-config": "config",
        "tailscale-beacon-k8s": "beacon",
    }
    root = roots[charm]
    terraform = TFManager(
        Path(__file__).parent / "terraform" / root, state_dir / f"{root}-{juju.model}.tfstate"
    )
    terraform.init()
    env = terraform_environment(juju)
    env.update({
        "TF_VAR_channel": os.environ.get("TAILSCALE_CHANNEL") or "dev/edge",
        "TF_VAR_config": json.dumps(config or {}),
    })
    terraform.apply(env)


def deploy_bookinfo(juju: jubilant.Juju, state_dir: Path, productpages: dict) -> None:
    """Deploy or scale Bookinfo without waiting for pending ingress credentials."""
    assert juju.model is not None
    terraform = TFManager(
        Path(__file__).parent / "terraform" / "bookinfo",
        state_dir / f"bookinfo-{juju.model}.tfstate",
    )
    terraform.init()
    env = terraform_environment(juju)
    env.update({
        "TF_VAR_channel": "latest/stable",
        "TF_VAR_productpages": json.dumps(productpages),
    })
    terraform.apply(env)
    juju.wait(
        lambda status: jubilant.all_active(status, "details", *productpages),
        timeout=1200, error=jubilant.any_error,
    )


def get_ingress_url(juju: jubilant.Juju, app: str) -> str | None:
    """Read the actual ingress relation, not the get-url action's local fallback."""
    data = json.loads(juju.cli("show-unit", f"{app}/0", "--format=json"))
    for relation in data[f"{app}/0"].get("relation-info", []):
        if relation["endpoint"] == "ingress":
            ingress = relation.get("application-data", {}).get("ingress")
            if ingress:
                return json.loads(ingress)["url"]
    return None


def request_productpage(juju: jubilant.Juju, app: str, dns_suffix: str) -> dict:
    """Fetch the published tailnet hostname with ordinary curl on the runner."""
    url = get_ingress_url(juju, app)
    assert url, f"No ingress URL published for {app}"
    parsed = urlsplit(url)
    assert parsed.scheme == "http" and parsed.hostname
    assert parsed.hostname.endswith("." + dns_suffix), "Ingress is not on the client's tailnet"
    return curl_from_host(urljoin(url, "/productpage"), no_proxy=True)


def proxy_pods(operator: jubilant.Juju, workload: jubilant.Juju, app: str) -> list[dict]:
    """Find this Service's proxies in the operator model."""
    assert operator.model is not None and workload.model is not None
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", operator.model.split(":")[-1], "-l",
         f"tailscale.com/parent-resource={app}-tailscale,"
         f"tailscale.com/parent-resource-ns={workload.model.split(':')[-1]},"
         "tailscale.com/parent-resource-type=svc", "-o", "json"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)["items"]


def wait_proxy_removed(operator: jubilant.Juju, workload: jubilant.Juju, app: str) -> None:
    """Allow the live operator to process its Service finalizer before teardown."""
    assert workload.model is not None
    subprocess.run(
        ["kubectl", "wait", "--for=delete", f"service/{app}-tailscale",
         "-n", workload.model.split(":")[-1], "--timeout=300s"],
        capture_output=True, text=True, check=True, timeout=310,
    )
    operator.wait(lambda _: not proxy_pods(operator, workload, app), timeout=300)


def get_credential_ids(provider: jubilant.Juju) -> set[str]:
    """Read the provider's peer map without retrieving secret contents."""
    data = json.loads(provider.cli("show-unit", "tailscale-config/0", "--format=json"))
    for relation in data["tailscale-config/0"].get("relation-info", []):
        if relation["endpoint"] == "credentials-map":
            mapping = relation.get("application-data", {}).get("credential-map", "{}")
            return set(json.loads(mapping).values())
    return set()


_access_token: dict[str, float | str] = {}


def _bearer_token(refresh: bool = False) -> str:
    """Reuse a short-lived access token instead of authenticating per request."""
    now = time.monotonic()
    if not refresh and float(_access_token.get("expiry", 0)) > now:
        return str(_access_token["token"])
    request = urllib.request.Request(
        "https://api.tailscale.com/api/v2/oauth/token",
        data=urlencode({
            "client_id": os.environ["TAILSCALE_CLIENT_ID"],
            "client_secret": os.environ["TAILSCALE_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        }).encode(),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
            token = payload["access_token"]
    except (urllib.error.URLError, KeyError, ValueError):
        raise RuntimeError("Tailscale OAuth authentication failed") from None
    _access_token.update(
        token=token, expiry=now + max(float(payload.get("expires_in", 3600)) - 60, 30)
    )
    return token


def tailscale_api(method: str, path: str) -> tuple[int, dict]:
    """Observe revocation and clean up nodes; credential minting stays in the charm."""
    for attempt in range(2):
        request = urllib.request.Request(
            f"https://api.tailscale.com/api/v2/{path}", method=method,
            headers={"Authorization": f"Bearer {_bearer_token(refresh=attempt > 0)}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                return response.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 404:
                return status, {}
            if status == 401 and attempt == 0:
                continue
            raise RuntimeError(f"Tailscale API returned HTTP {status}") from None
        except urllib.error.URLError:
            raise RuntimeError("Could not reach the Tailscale API") from None
    raise RuntimeError("Tailscale API authentication was rejected")


def credential_revoked(key: str) -> bool:
    """Check revocation independently of the provider's reported status.

    A revoked key keeps its record, reported as revoked and invalid, so absence
    alone is not a sufficient signal.
    """
    status, data = tailscale_api("GET", "tailnet/-/keys/" + quote(key, safe=""))
    return status == 404 or bool(data.get("revoked")) or bool(data.get("invalid"))


def remove_tailnet_devices(hostnames: set[str]) -> None:
    """Delete only exact, unique device names belonging to this scenario."""
    _, data = tailscale_api("GET", "tailnet/-/devices")
    for device in data["devices"]:
        if device["hostname"] in hostnames:
            tailscale_api("DELETE", "device/" + quote(str(device["id"]), safe=""))
