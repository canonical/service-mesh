"""Step definitions for Istio integration tests."""

import logging
from typing import Dict

import jubilant
from pytest_bdd import given, parsers, then, when

from tests.integration.istio.helpers import (
    curl_service,
    deploy_bookinfo,
    deploy_istio_beacon,
    scale_application,
    wait_for_active_idle_without_error,
)

logger = logging.getLogger(__name__)


# -------------- Given --------------


@given(parsers.parse("the bookinfo services are deployed {mesh_enabled}"))
def bookinfo_services_deployed(mesh_enabled: str, juju: jubilant.Juju, beacon_info: Dict):
    """Ensure the bookinfo services are deployed with the specified service_mesh setting."""
    enable_istio = mesh_enabled.lower() == "with istio-beacon-k8s integration"
    logger.info(f"Bookinfo services deployed with service_mesh={enable_istio}")

    if enable_istio:
        app_name, endpoint = deploy_istio_beacon(juju)
        beacon_info["app_name"] = app_name
        beacon_info["endpoint"] = endpoint
        deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    else:
        deploy_bookinfo(juju)


# -------------- When --------------


@when(parsers.parse("you deploy the bookinfo services {mesh_enabled}"))
def deploy_bookinfo_services(mesh_enabled: str, juju: jubilant.Juju, beacon_info: Dict):
    """Deploy the bookinfo services with the specified service_mesh setting."""
    enable_istio = mesh_enabled.lower() == "with istio-beacon-k8s integration"
    logger.info(f"Deploying bookinfo services with istio_enabled={enable_istio}")

    if enable_istio:
        app_name, endpoint = deploy_istio_beacon(juju)
        beacon_info["app_name"] = app_name
        beacon_info["endpoint"] = endpoint
        deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    else:
        deploy_bookinfo(juju)


@when("productpage calls the details service")
def productpage_calls_details(juju: jubilant.Juju, juju_run_output: dict):
    """Test connectivity from productpage to details service using curl."""
    result = curl_service(
        juju=juju, unit="productpage/0", service_url="http://details:9080/details/0"
    )
    juju_run_output["last_request"] = result
    logger.info(f"Productpage -> Details curl result: {result['stdout']}")


@when(parsers.parse("you scale {app_name} to {units} unit"))
@when(parsers.parse("you scale {app_name} to {units} units"))
def scale_app(app_name: str, units: str, juju: jubilant.Juju, beacon_info: Dict):
    """Scale a bookinfo application to the specified number of units."""
    logger.info(f"Scaling {app_name} to {int(units)} units")
    scale_application(
        juju,
        app_name,
        int(units),
        beacon_app_name=beacon_info["app_name"],
        beacon_service_mesh_endpoint=beacon_info["endpoint"],
    )
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


# -------------- Then --------------


@then("all charms are active")
def all_charms_active(juju: jubilant.Juju):
    """Verify all deployed charms are in active state."""
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


@then("details returns valid book information")
def details_returns_book_info(juju_run_output: dict):
    """Verify the details service returned valid book information."""
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    stdout = result["stdout"]
    # Check for expected book information fields (JSON response)
    assert any(field in stdout for field in ["id", "type", "year", "ISBN"]), (
        f"Response missing book information: {stdout}"
    )
    logger.info(f"Details response: {stdout}")
