"""Step definitions for managed mode tests."""

import logging
from typing import Dict

import jubilant
from pytest_bdd import given, parsers, then

from tests.integration.helpers import (
    wait_for_active_idle_without_error,
)
from tests.integration.istio.helpers import (
    deploy_bookinfo,
    deploy_istio_beacon,
    get_authorization_policies,
)

logger = logging.getLogger(__name__)


# -------------- Given --------------


@given(parsers.parse("istio-beacon-k8s has manage-authorization-policies set to {value}"))
def configure_beacon_managed_mode(value: str, juju: jubilant.Juju, beacon_info: Dict):
    """Configure istio-beacon's manage-authorization-policies setting."""
    logger.info(f"Redeploying beacon with manage-authorization-policies={value}")

    app_name, endpoint = deploy_istio_beacon(juju, config={"manage-authorization-policies": value})
    beacon_info["app_name"] = app_name
    beacon_info["endpoint"] = endpoint
    deploy_bookinfo(juju, beacon_app_name=app_name, beacon_service_mesh_endpoint=endpoint)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


# -------------- Then --------------


@then("istio-beacon-k8s has created authorization policies")
def istio_beacon_created_authorization_policies(juju: jubilant.Juju):
    """Verify that istio-beacon has created authorization policies in the namespace."""
    policies = get_authorization_policies(juju)
    assert len(policies) > 0, (
        "Expected istio-beacon to create authorization policies, but found none"
    )
    logger.info(f"Confirmed istio-beacon created authorization policies: {policies}")


@then("istio-beacon-k8s has not created authorization policies")
def istio_beacon_not_created_authorization_policies(juju: jubilant.Juju):
    """Verify that istio-beacon has not created any authorization policies in the namespace."""
    policies = get_authorization_policies(juju)
    assert len(policies) == 0, (
        f"Expected istio-beacon not to create authorization policies, but found: {policies}"
    )
    logger.info("Confirmed istio-beacon has not created authorization policies")
