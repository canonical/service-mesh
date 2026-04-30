"""Helper functions for Service Mesh integration tests."""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import jubilant

from tests.integration.helpers import TFManager, wait_for_active_idle_without_error

logger = logging.getLogger(__name__)

ISTIO_INGRESS_K8S_SERVICE_NAME = "istio-ingress-k8s-istio"


def get_gateway_address(namespace: str) -> str:
    """Get the external address of the ingress gateway LoadBalancer Service.

    Args:
        namespace: The Kubernetes namespace (Juju model name)

    Returns:
        The LoadBalancer external IP address

    Raises:
        RuntimeError: If no external IP is found
    """
    # Use kubectl instead of lightkube because MicroK8s CA certs lack the key usage
    # extension, which causes SSL verification failures with OpenSSL 3.5+.
    # See: https://github.com/canonical/microk8s/issues/4864
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "svc",
            ISTIO_INGRESS_K8S_SERVICE_NAME,
            "-n",
            namespace,
            "-o",
            "jsonpath={.status.loadBalancer.ingress[0].ip}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"No external IP found for {ISTIO_INGRESS_K8S_SERVICE_NAME} in {namespace}: "
            f"{result.stderr}"
        )
    return result.stdout.strip()


# Istio configuration
# Version 2 doesn't work with iam so running dev for now. We can consider switching to a stable track when a new one releases.
ISTIO_CHANNEL = os.environ.get("ISTIO_CHANNEL", "dev/edge")


def get_authorization_policies(juju: jubilant.Juju) -> List[str]:
    """Get list of AuthorizationPolicy resources in the model's namespace.

    Args:
        juju: The Juju model instance

    Returns:
        List of AuthorizationPolicy names
    """
    assert juju.model is not None, "Juju model is not set"

    # Use kubectl instead of lightkube because MicroK8s CA certs lack the key usage
    # extension, which causes SSL verification failures with OpenSSL 3.5+.
    # See: https://github.com/canonical/microk8s/issues/4864
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "authorizationpolicies.security.istio.io",
                "-n",
                juju.model,
                "-o",
                "jsonpath={.items[*].metadata.name}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"Failed to get authorization policies: {result.stderr}")
            return []
        policy_names = result.stdout.strip().split() if result.stdout.strip() else []
        logger.info(
            f"Found {len(policy_names)} authorization policies in {juju.model}: {policy_names}"
        )
        return policy_names
    except Exception as e:
        logger.error(f"Failed to get authorization policies: {e}")
        return []


def deploy_istio(juju: jubilant.Juju, config: Optional[dict] = None) -> None:
    """Deploy istio-k8s to a Juju model using terraform.

    Args:
        juju: The Juju model instance to deploy to
        config: Optional configuration dict for the charm
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "istio"
    state_file = Path(tempfile.gettempdir()) / f"istio-{juju.model}.tfstate"

    logger.info(f"Deploying istio-k8s to {juju.model} (channel={ISTIO_CHANNEL}, config={config})")

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": ISTIO_CHANNEL,
        }
    )
    if config:
        env["TF_VAR_config"] = json.dumps(config)
    terraform.apply(env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


def deploy_istio_beacon(juju: jubilant.Juju, config: Optional[dict] = None) -> tuple[str, str]:
    """Deploy istio-beacon to a Juju model using terraform and return app name and endpoint.

    Args:
        juju: The Juju model instance to deploy to
        config: Optional configuration dict for the charm

    Returns:
        Tuple of (app_name, service_mesh_endpoint)
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "istio-beacon"
    state_file = Path(tempfile.gettempdir()) / f"istio-beacon-{juju.model}.tfstate"

    logger.info(
        f"Deploying istio-beacon to {juju.model} (channel={ISTIO_CHANNEL}, config={config})"
    )

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": ISTIO_CHANNEL,
        }
    )
    if config:
        env["TF_VAR_config"] = json.dumps(config)
    terraform.apply(env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)
    # Get the beacon app name and service mesh endpoint from terraform output
    app_name = terraform.output("app_name")
    service_mesh_endpoint = terraform.output("service_mesh_endpoint")
    logger.info(f"Istio-beacon deployed: app={app_name}, endpoint={service_mesh_endpoint}")

    return app_name, service_mesh_endpoint


def deploy_istio_ingress(juju: jubilant.Juju, config: Optional[dict] = None) -> str:
    """Deploy istio-ingress-k8s to a Juju model using terraform.

    Args:
        juju: The Juju model instance to deploy to
        config: Optional configuration dict for the charm

    Returns:
        The app name
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "istio-ingress"
    state_file = Path(tempfile.gettempdir()) / f"istio-ingress-{juju.model}.tfstate"

    logger.info(
        f"Deploying istio-ingress-k8s to {juju.model} (channel={ISTIO_CHANNEL}, config={config})"
    )

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": ISTIO_CHANNEL,
        }
    )
    if config:
        env["TF_VAR_config"] = json.dumps(config)
    terraform.apply(env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)

    app_name = terraform.output("app_name")
    logger.info(f"Istio-ingress deployed: app={app_name}")

    return app_name


def deploy_iam(juju: jubilant.Juju) -> dict:
    """Deploy the Canonical Identity Platform using terraform.

    Args:
        juju: The Juju model instance to deploy into

    Returns:
        Dictionary with offer URLs: oauth_offer_url, send_ca_cert_offer_url, certificates_offer_url
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "iam"
    state_file = Path(tempfile.gettempdir()) / f"iam-{juju.model}.tfstate"

    logger.info(f"Deploying the Canonical Identity Platform to model {juju.model}")

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    env = os.environ.copy()
    env["TF_VAR_model"] = juju.model
    terraform.apply(env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)

    return {
        "oauth_offer_url": terraform.output("oauth_offer_url"),
        "send_ca_cert_offer_url": terraform.output("send_ca_cert_offer_url"),
        "certificates_offer_url": terraform.output("certificates_offer_url"),
    }


def deploy_oauth2_proxy(juju: jubilant.Juju, config: Optional[dict] = None) -> str:
    """Deploy oauth2-proxy-k8s to a Juju model using terraform.

    Args:
        juju: The Juju model instance to deploy to
        config: Optional configuration dict for the charm

    Returns:
        The app name
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "oauth2-proxy"
    state_file = Path(tempfile.gettempdir()) / f"oauth2-proxy-{juju.model}.tfstate"

    logger.info(f"Deploying oauth2-proxy-k8s to {juju.model} (config={config})")

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    env = os.environ.copy()
    env["TF_VAR_model"] = juju.model
    if config:
        env["TF_VAR_config"] = json.dumps(config)
    terraform.apply(env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)

    app_name = terraform.output("app_name")
    logger.info(f"OAuth2-proxy deployed: app={app_name}")

    return app_name


def deploy_bookinfo(
    juju: jubilant.Juju,
    beacon_app_name: Optional[str] = None,
    beacon_service_mesh_endpoint: Optional[str] = None,
) -> None:
    """Deploy the bookinfo stack to a Juju model using terraform.

    Args:
        juju: The Juju model instance to deploy to
        beacon_app_name: Optional name of the istio-beacon application. If provided, enables service mesh integration.
        beacon_service_mesh_endpoint: Optional endpoint name for beacon's service mesh integration.
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "bookinfo"
    state_file = Path(tempfile.gettempdir()) / f"bookinfo-{juju.model}.tfstate"

    logger.info(
        f"Deploying bookinfo to {juju.model} (beacon={beacon_app_name}, endpoint={beacon_service_mesh_endpoint})"
    )

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": "latest/stable",
        }
    )

    if beacon_app_name:
        env["TF_VAR_beacon_app_name"] = beacon_app_name
    if beacon_service_mesh_endpoint:
        env["TF_VAR_beacon_service_mesh_endpoint"] = beacon_service_mesh_endpoint

    terraform.apply(env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


def scale_bookinfo_application(
    juju: jubilant.Juju,
    app_name: str,
    units: int,
    beacon_app_name: Optional[str] = None,
    beacon_service_mesh_endpoint: Optional[str] = None,
) -> None:
    """Scale a bookinfo application using terraform.

    Args:
        juju: The Juju model instance
        app_name: The name of the application to scale (e.g., "productpage", "details")
        units: The desired number of units
        beacon_app_name: Optional name of the istio-beacon application
        beacon_service_mesh_endpoint: Optional endpoint name for beacon's service mesh integration
    """
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent / "terraform" / "bookinfo"
    state_file = Path(tempfile.gettempdir()) / f"bookinfo-{juju.model}.tfstate"

    logger.info(f"Scaling {app_name} to {units} units")

    terraform = TFManager(terraform_dir, state_file)
    terraform.init()

    # Build terraform variables
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": "latest/stable",
            f"TF_VAR_{app_name}": json.dumps({"units": units}),
        }
    )

    if beacon_app_name:
        env["TF_VAR_beacon_app_name"] = beacon_app_name
    if beacon_service_mesh_endpoint:
        env["TF_VAR_beacon_service_mesh_endpoint"] = beacon_service_mesh_endpoint

    terraform.apply(env)
