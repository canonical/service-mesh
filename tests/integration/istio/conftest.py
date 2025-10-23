"""Pytest configuration for Service Mesh integration tests."""

import logging
from typing import Dict

import jubilant
import pytest
from helpers import (
    curl_service,
    deploy_bookinfo,
    deploy_istio,
    deploy_istio_beacon,
    get_authorization_policies,
    verify_http_response,
    wait_for_active_idle_without_error,
)
from pytest_bdd import given, parsers, then, when

logger = logging.getLogger(__name__)


# -------------- Fixtures --------------


@pytest.fixture(scope="module")
def istio_system_juju(temp_model_factory):
    """Create a temporary Juju model for istio-system deployment."""
    yield temp_model_factory.get_juju(suffix="istio-system")


@pytest.fixture
def juju_run_output() -> Dict:
    """Store the output from juju run actions."""
    return {}


@pytest.fixture(scope="module")
def beacon_info() -> Dict:
    """Store the beacon app name and endpoint for the test module."""
    return {"app_name": None, "endpoint": None}


# -------------- Shared Definitions --------------


@given("an istio-system model with istio-k8s deployed")
def istio_system_deployed(istio_system_juju: jubilant.Juju):
    """Ensure the istio-system model exists with istio-k8s deployed."""
    assert istio_system_juju.model is not None
    logger.info(f"Istio-system model created: {istio_system_juju.model}")

    deploy_istio(istio_system_juju)


@given("a juju model with bookinfo services")
def juju_model_bookinfo_services(juju: jubilant.Juju):
    """Ensure a Juju model exists for bookinfo services."""
    assert juju.model is not None
    logger.info(f"Bookinfo model created: {juju.model}")


@given("the bookinfo services are deployed with istio")
def bookinfo_services_deployed_with_istio(juju: jubilant.Juju, beacon_info: Dict):
    """Ensure the bookinfo services are deployed with istio enabled."""
    logger.info("Deploying istio-beacon and bookinfo services")
    app_name, endpoint = deploy_istio_beacon(juju)
    beacon_info["app_name"] = app_name
    beacon_info["endpoint"] = endpoint
    deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


@when(parsers.parse("productpage requests {method} {path} on {service}"))
def productpage_requests_service(
    method: str, path: str, service: str, juju: jubilant.Juju, juju_run_output: dict
):
    """Test HTTP request from productpage to a service with specified method and path."""
    service_url = f"http://{service}{path}"
    logger.info(f"Productpage -> {method} {service_url}")

    result = curl_service(juju=juju, unit="productpage/0", service_url=service_url, method=method)
    juju_run_output["last_request"] = result
    logger.info(f"Request result: HTTP_CODE in stdout: {result['stdout']}")


@then("the request succeeds")
def request_succeeds(juju_run_output: dict):
    """Verify the last request succeeded with HTTP 200."""
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    verify_http_response(result, expected_http_code=200, expected_exit_code=0)


@then("the request is rejected")
def request_is_rejected(juju_run_output: dict):
    """Verify the last request was rejected with exit_code 1."""
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    verify_http_response(result, expected_exit_code=1)


# -------------- Istio Integration Definitions --------------


@when(parsers.parse("you deploy the bookinfo services {mesh_enabled}"))
def deploy_bookinfo_services(mesh_enabled: str, juju: jubilant.Juju, beacon_info: Dict):
    """Deploy the bookinfo services with the specified service_mesh setting."""
    enable_istio = mesh_enabled.lower() == "with istio"
    logger.info(f"Deploying bookinfo services with istio_enabled={enable_istio}")

    if enable_istio:
        app_name, endpoint = deploy_istio_beacon(juju)
        beacon_info["app_name"] = app_name
        beacon_info["endpoint"] = endpoint
        deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    else:
        deploy_bookinfo(juju)


@given(parsers.parse("the bookinfo services are deployed {mesh_enabled}"))
def bookinfo_services_deployed(mesh_enabled: str, juju: jubilant.Juju, beacon_info: Dict):
    """Ensure the bookinfo services are deployed with the specified service_mesh setting."""
    enable_istio = mesh_enabled.lower() == "with istio"
    logger.info(f"Bookinfo services deployed with service_mesh={enable_istio}")

    if enable_istio:
        app_name, endpoint = deploy_istio_beacon(juju)
        beacon_info["app_name"] = app_name
        beacon_info["endpoint"] = endpoint
        deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    else:
        deploy_bookinfo(juju)


@then("all charms are active")
def all_charms_active(juju: jubilant.Juju):
    """Verify all deployed charms are in active state."""
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


@when("productpage calls the details service")
def productpage_calls_details(juju: jubilant.Juju, juju_run_output: dict):
    """Test connectivity from productpage to details service using curl."""
    result = curl_service(
        juju=juju, unit="productpage/0", service_url="http://details:9080/details/0"
    )
    juju_run_output["details"] = result
    logger.info(f"Productpage -> Details curl result: {result['stdout']}")


@then("details returns valid book information")
def details_returns_book_info(juju_run_output: dict):
    """Verify the details service returned valid book information."""
    result = juju_run_output.get("details")
    assert result is not None, "No details result found"

    stdout = result["stdout"]
    # Check for expected book information fields (JSON response)
    assert any(field in stdout for field in ["id", "type", "year", "ISBN"]), (
        f"Response missing book information: {stdout}"
    )
    logger.info(f"Details response: {stdout}")


@when(parsers.parse("you scale {app_name} to {units} unit"))
@when(parsers.parse("you scale {app_name} to {units} units"))
def scale_app(app_name: str, units: str, juju: jubilant.Juju, beacon_info: Dict):
    """Scale a bookinfo application to the specified number of units."""
    from helpers import scale_application

    logger.info(f"Scaling {app_name} to {int(units)} units")
    scale_application(
        juju,
        app_name,
        int(units),
        beacon_app_name=beacon_info["app_name"],
        beacon_service_mesh_endpoint=beacon_info["endpoint"],
    )
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


# -------------- Authorization Policies Definitions --------------


@then("the request is forbidden")
def request_is_forbidden(juju_run_output: dict):
    """Verify the last request was forbidden with HTTP 403."""
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    verify_http_response(result, expected_http_code=403, expected_exit_code=0)


# -------------- Managed Mode Definitions --------------


@given(parsers.parse("istio-beacon has manage-authorization-policies set to {value}"))
def configure_beacon_managed_mode(value: str, juju: jubilant.Juju, beacon_info: Dict):
    """Configure istio-beacon's manage-authorization-policies setting."""
    managed_mode = value.lower() == "true"
    logger.info(f"Redeploying beacon with manage-authorization-policies={managed_mode}")

    app_name, endpoint = deploy_istio_beacon(juju, managed_mode=managed_mode)
    beacon_info["app_name"] = app_name
    beacon_info["endpoint"] = endpoint
    deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


@then("istio-beacon has created authorization policies")
def istio_beacon_created_authorization_policies(juju: jubilant.Juju):
    """Verify that istio-beacon has created authorization policies in the namespace."""
    policies = get_authorization_policies(juju)
    assert len(policies) > 0, "Expected istio-beacon to create authorization policies, but found none"
    logger.info(f"Confirmed istio-beacon created authorization policies: {policies}")


@then("istio-beacon has not created authorization policies")
def istio_beacon_not_created_authorization_policies(juju: jubilant.Juju):
    """Verify that istio-beacon has not created any authorization policies in the namespace."""
    policies = get_authorization_policies(juju)
    assert len(policies) == 0, f"Expected istio-beacon not to create authorization policies, but found: {policies}"
    logger.info("Confirmed istio-beacon has not created authorization policies")
