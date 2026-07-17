"""Test helpers that should be moved to an external package in future for sharing."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import lightkube
import yaml
from lightkube.resources.core_v1 import Service

logger = logging.getLogger(__name__)

app_metadata = yaml.safe_load(Path("./charmcraft.yaml").read_text())
KIALI_NAME = app_metadata["name"]
kiali_resources = {
    "kiali-image": app_metadata["resources"]["kiali-image"]["upstream-source"],
}


@dataclass
class CharmDeploymentConfiguration:
    entity_url: str  # aka charm name or local path to charm
    application_name: str
    channel: str
    trust: bool
    revision: Optional[int] = None
    config: Optional[dict] = None


ISTIO_K8S = CharmDeploymentConfiguration(
    entity_url="istio-k8s", application_name="istio-k8s", channel="2/edge", trust=True
)
ISTIO_INGRESS_K8S = CharmDeploymentConfiguration(
    entity_url="istio-ingress-k8s",
    application_name="istio-ingress-k8s",
    channel="2/edge",
    trust=True,
)
PROMETHEUS_K8S = CharmDeploymentConfiguration(
    entity_url="prometheus-k8s",
    application_name="prometheus-k8s",
    channel="2/edge",
    trust=True,
)


def get_k8s_service_ip(namespace: str, service_name: str) -> Optional[str]:
    """Get the ClusterIP or LoadBalancer IP of a Kubernetes service using lightkube.

    Args:
        namespace: The namespace of the Kubernetes service.
        service_name: The name of the Kubernetes service.

    Returns:
        The LoadBalancer IP if the service type is LoadBalancer and has an IP,
        otherwise the ClusterIP. Returns None if the service is not found or no IP is available.
    """
    try:
        c = lightkube.Client()
        svc = c.get(Service, namespace=namespace, name=service_name)

        if svc.spec.type == "LoadBalancer":
            ingress = svc.status.loadBalancer.ingress
            if ingress and len(ingress) > 0 and hasattr(ingress[0], "ip"):
                return ingress[0].ip

        return svc.spec.clusterIP

    except Exception as e:
        logger.error("Error retrieving service address %s", e, exc_info=1)
        return None
