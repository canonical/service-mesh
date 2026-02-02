"""Helper functions for Service Mesh integration tests."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional

import jubilant
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.core_v1 import Service

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
    client = Client()
    svc = client.get(Service, name=ISTIO_INGRESS_K8S_SERVICE_NAME, namespace=namespace)
    if (
        svc.status is None
        or svc.status.loadBalancer is None
        or not svc.status.loadBalancer.ingress
    ):
        raise RuntimeError(
            f"No external IP found for {ISTIO_INGRESS_K8S_SERVICE_NAME} in {namespace}"
        )
    return str(svc.status.loadBalancer.ingress[0].ip)


_AuthorizationPolicy = create_namespaced_resource(
    group="security.istio.io",
    version="v1beta1",
    kind="AuthorizationPolicy",
    plural="authorizationpolicies",
)


# Istio configuration
ISTIO_CHANNEL = os.environ.get("ISTIO_CHANNEL", "2/edge")


def get_authorization_policies(juju: jubilant.Juju) -> List[str]:
    """Get list of AuthorizationPolicy resources in the model's namespace.

    Args:
        juju: The Juju model instance

    Returns:
        List of AuthorizationPolicy names
    """
    assert juju.model is not None, "Juju model is not set"

    try:
        client = Client()
        policies = client.list(_AuthorizationPolicy, namespace=juju.model)
        policy_names = [
            policy.metadata.name
            for policy in policies
            if policy.metadata is not None and policy.metadata.name is not None
        ]
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
