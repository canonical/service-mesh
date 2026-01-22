"""Step definitions for hardened mode tests."""

import logging
from typing import Dict

import jubilant
from pytest_bdd import given, parsers, when

from tests.integration.helpers import (
    curl_from_juju_unit,
    wait_for_active_idle_without_error,
)
from tests.integration.istio.helpers import deploy_istio_ingress

logger = logging.getLogger(__name__)


# -------------- Given --------------


@given("istio-ingress-k8s is deployed")
def istio_ingress_deployed(juju: jubilant.Juju, ingress_info: Dict):
    """Deploy istio-ingress-k8s to the model."""
    logger.info(f"Deploying istio-ingress-k8s to {juju.model}")
    app_name = deploy_istio_ingress(juju)
    ingress_info["app_name"] = app_name


@given("productpage is exposed via ingress")
def productpage_exposed_via_ingress(juju: jubilant.Juju, ingress_info: Dict):
    """Create ingress relation to expose productpage."""
    ingress_app = ingress_info["app_name"]
    assert ingress_app is not None, "Ingress app not deployed"
    logger.info(f"Relating productpage to {ingress_app}")
    juju.cli("relate", "productpage:ingress", f"{ingress_app}:ingress")
    wait_for_active_idle_without_error([juju], timeout=60 * 10)


# -------------- When --------------


@when(parsers.parse("external client requests {method} {path} on the ingress gateway"))
def external_client_requests_ingress(
    method: str, path: str, juju: jubilant.Juju, ingress_info: Dict, juju_run_output: dict
):
    """Test HTTP request from outside the cluster via ingress gateway."""
    ingress_app = ingress_info["app_name"]
    assert ingress_app is not None, "Ingress app not deployed"
    # Get the ingress gateway URL from juju status
    status = juju.status()
    ingress_address = status.apps[ingress_app].address
    url = f"http://{ingress_address}{path}"
    logger.info(f"External client -> {method} {url}")

    # Use curl from productpage unit to reach the ingress gateway
    result = curl_from_juju_unit(juju=juju, unit="productpage/0", url=url, method=method)
    juju_run_output["last_request"] = result
    logger.info(f"Request result: HTTP_CODE in stdout: {result['stdout']}")
