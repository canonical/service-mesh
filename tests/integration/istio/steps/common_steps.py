"""Common step definitions shared across multiple features."""

import logging
from typing import Dict

import jubilant
from pytest_bdd import given, parsers, then, when

from tests.integration.helpers import (
    curl_from_juju_unit,
    verify_http_response,
    wait_for_active_idle_without_error,
)
from tests.integration.istio.helpers import (
    deploy_bookinfo,
    deploy_istio,
    deploy_istio_beacon,
    deploy_istio_ingress,
)

logger = logging.getLogger(__name__)


# -------------- Given --------------


@given("a juju model with istio-k8s deployed")
def istio_system_deployed(istio_system_juju: jubilant.Juju):
    """Ensure the istio-system model exists with istio-k8s deployed."""
    assert istio_system_juju.model is not None
    logger.info(f"Istio-system model created: {istio_system_juju.model}")

    deploy_istio(istio_system_juju)


@given("a juju model for bookinfo services")
def juju_model_bookinfo_services(juju: jubilant.Juju):
    """Ensure a Juju model exists for bookinfo services."""
    assert juju.model is not None
    logger.info(f"Bookinfo model created: {juju.model}")


@given("the bookinfo services are deployed with istio-beacon-k8s integration")
def bookinfo_services_deployed_with_istio_beacon(
    juju: jubilant.Juju, beacon_info: Dict, beacon_config: Dict
):
    """Ensure the bookinfo services are deployed with istio-beacon-k8s integration enabled."""
    logger.info(f"Deploying istio-beacon (config={beacon_config}) and bookinfo services")
    app_name, endpoint = deploy_istio_beacon(juju, config=beacon_config if beacon_config else None)
    beacon_info["app_name"] = app_name
    beacon_info["endpoint"] = endpoint
    deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


@given(parsers.parse("{charm} has {config} set to {value}"))
def charm_has_config_set(
    charm: str,
    config: str,
    value: str,
    juju: jubilant.Juju,
    istio_system_juju: jubilant.Juju,
    beacon_info: Dict,
    ingress_info: Dict,
    istio_config: Dict,
    beacon_config: Dict,
    ingress_config: Dict,
):
    """Set a config option on a charm by redeploying with the new config via terraform."""
    logger.info(f"Setting {charm} config: {config}={value}")

    if charm == "istio-k8s":
        istio_config[config] = value
        deploy_istio(istio_system_juju, config=istio_config)
    elif charm == "istio-beacon-k8s":
        beacon_config[config] = value
        app_name, endpoint = deploy_istio_beacon(juju, config=beacon_config)
        beacon_info["app_name"] = app_name
        beacon_info["endpoint"] = endpoint
    elif charm == "istio-ingress-k8s":
        ingress_config[config] = value
        app_name = deploy_istio_ingress(juju, config=ingress_config)
        ingress_info["app_name"] = app_name


# -------------- When --------------


@when(parsers.parse("{app} requests {method} {path} on {service}"))
def app_requests_service(
    app: str, method: str, path: str, service: str, juju: jubilant.Juju, juju_run_output: dict
):
    """Test HTTP request from an app to a service with specified method and path."""
    service_url = f"http://{service}{path}"
    logger.info(f"{app} -> {method} {service_url}")

    result = curl_from_juju_unit(juju=juju, unit=f"{app}/0", url=service_url, method=method)
    juju_run_output["last_request"] = result
    logger.info(f"Request result: HTTP_CODE in stdout: {result['stdout']}")


# -------------- Then --------------


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


@then("the request is unavailable")
def request_is_unavailable(juju_run_output: dict):
    """Verify the last request returned 503 Service Unavailable."""
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    verify_http_response(result, expected_http_code=503, expected_exit_code=0)
