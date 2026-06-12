#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from jubilant import Juju
from lightkube.core.client import Client
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.autoscaling_v2 import HorizontalPodAutoscaler
from lightkube.resources.core_v1 import Namespace
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
SENDER = "sender"
RECEIVER = "receiver"
RESOURCES = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}


@dataclass
class CharmDeploymentConfiguration:
    entity_url: str  # aka charm name or local path to charm
    application_name: str
    channel: str
    trust: bool
    config: Optional[dict] = None


istio_k8s = CharmDeploymentConfiguration(
    entity_url="istio-k8s", application_name="istio-k8s", channel="dev/edge", trust=True
)


AuthPolicy = create_namespaced_resource(
    "security.istio.io", "v1", "AuthorizationPolicy", "authorizationpolicies"
)


def get_hpa(model_name: str, hpa_name: str) -> Optional[HorizontalPodAutoscaler]:
    """Retrieve the HPA resource so we can inspect .spec and .status directly.

    Args:
        model_name: Juju model name (K8s namespace).
        hpa_name: Name of the HPA resource.

    Returns:
        The HorizontalPodAutoscaler object or None if not found / on error.
    """
    try:
        c = Client()
        return c.get(HorizontalPodAutoscaler, namespace=model_name, name=hpa_name)
    except Exception as e:
        logger.error("Error retrieving HPA %s: %s", hpa_name, e, exc_info=True)
        return None


def validate_labels(juju: Juju, app_name: str, should_be_present: bool):
    """Validate the presence or absence of specific labels in the namespace.

    Args:
        juju: Juju instance.
        app_name: Name of the application.
        should_be_present: Whether the labels should be present or absent.
    """
    model_name = juju.model
    assert model_name is not None
    client = Client()
    namespace = client.get(Namespace, model_name)

    expected_labels = {
        "istio.io/use-waypoint": f"{model_name}-{app_name}-waypoint",
        "istio.io/dataplane-mode": "ambient",
        "charms.canonical.com/istio.io.waypoint.managed-by": f"{model_name}.{app_name}",
    }

    for label, expected_value in expected_labels.items():
        assert namespace.metadata
        assert namespace.metadata.labels
        actual_value = namespace.metadata.labels.get(label)
        if should_be_present:
            assert actual_value == expected_value, f"Label {label} is missing or incorrect."
        else:
            assert actual_value is None, f"Label {label} should have been removed."


def validate_policy_exists(juju: Juju, policy_name: str):
    """Validate that an AuthorizationPolicy exists in the namespace.

    Args:
        juju: Juju instance.
        policy_name: Name of the policy to check.
    """
    model_name = juju.model
    assert model_name is not None
    client = Client()
    client.get(AuthPolicy, policy_name, namespace=model_name)


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(120), reraise=True
)
def assert_request_returns_http_code(
    juju: Juju, source_unit: str, target_url: str, method: str = "get", code: int = 200
):
    """Get the status code for a request from a source unit to a target URL on a given method.

    Note that if the request fails (ex: curl raises an exception) the exit code will be returned.

    Args:
        juju: Juju instance.
        source_unit: Source unit name (e.g., "app/0").
        target_url: Target URL to request.
        method: HTTP method (get, post, etc.).
        code: Expected HTTP status code.
    """
    logger.info(f"Checking {source_unit} -> {target_url} on {method}")
    try:
        resp = juju.ssh(
            source_unit,
            f'curl -X {method.upper()} -s -o /dev/null -w "%{{http_code}}" {target_url}',
        )
        returned_code = int(resp.strip())
    except Exception as e:
        logger.warning(f"Got exception executing juju.ssh: {e}")
        # Treat SSH failures as exit code 1
        returned_code = 1

    logger.info(
        f"Got {returned_code} for {source_unit} -> {target_url} on {method} - expected {code}"
    )

    assert (
        returned_code == code
    ), f"Expected {code} but got {returned_code} for {source_unit} -> {target_url} on {method}"


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(120), reraise=True
)
def assert_tcp_connectivity(
    juju: Juju, source_unit: str, host: str, port: int, inverse_check: bool = False
):
    """Test TCP connectivity from source unit to target host:port using /dev/tcp.

    Args:
        juju: Juju instance.
        source_unit: Source unit name (e.g., "sender/0").
        host: Target hostname or IP.
        port: Target port number.
        inverse_check: Pass if the connection fails.
    """
    cmd = f'timeout 5 bash -c "echo >/dev/tcp/{host}/{port}"'

    try:
        juju.ssh(source_unit, cmd)
        exit_code = 0
        logger.info(f"TCP connectivity test succeeded: {source_unit} -> {host}:{port}")
    except Exception as e:
        exit_code = 1
        logger.info(
            f"TCP connectivity test failed: {source_unit} -> {host}:{port} - {e}"
        )

    if not inverse_check:
        assert (
            exit_code == 0
        ), f"Expected TCP connection to {host}:{port} to succeed, but it failed"
    else:
        assert (
            exit_code != 0
        ), f"Expected TCP connection to {host}:{port} to fail, but it succeeded"


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_delay(120), reraise=True
)
def validate_mesh_labels_on_consumer(
    juju: Juju, beacon_app: str, consumer_app: str, should_be_present: bool
):
    """Validate the presence or absence of mesh labels on a consumer app's StatefulSet pod template.

    Args:
        juju: Juju instance.
        beacon_app: Name of the beacon application providing mesh labels.
        consumer_app: Name of the consumer application to check.
        should_be_present: Whether the mesh labels should be present or absent.
    """
    model_name = juju.model
    assert model_name is not None
    client = Client()
    sts = client.get(StatefulSet, consumer_app, namespace=model_name)

    expected_labels = {
        "istio.io/dataplane-mode": "ambient",
        "istio.io/use-waypoint": f"{model_name}-{beacon_app}-waypoint",
        "istio.io/use-waypoint-namespace": model_name,
    }

    assert sts.spec and sts.spec.template.metadata
    pod_labels = sts.spec.template.metadata.labels or {}

    for label, expected_value in expected_labels.items():
        actual_value = pod_labels.get(label)
        if should_be_present:
            assert actual_value == expected_value, (
                f"Mesh label {label} is missing or incorrect on {consumer_app} StatefulSet. "
                f"Expected {expected_value!r}, got {actual_value!r}"
            )
        else:
            assert actual_value is None, (
                f"Mesh label {label} should have been removed from {consumer_app} StatefulSet"
            )


def scale_application(juju: Juju, app_name: str, target_units: int):
    """Scale an application to the target number of units.

    Args:
        juju: Juju instance.
        app_name: Name of the application to scale.
        target_units: Target number of units.
    """
    status = juju.status()
    current_count = len(status.apps[app_name].units)

    if target_units > current_count:
        # Scale up
        juju.add_unit(app_name, num_units=target_units - current_count)
    elif target_units < current_count:
        # Scale down - K8s models require --num-units, not named units
        juju.remove_unit(app_name, num_units=current_count - target_units)
