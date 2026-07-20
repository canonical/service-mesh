# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Workload (Pebble) steps for the envoy-controller-k8s suite."""

from jubilant import Juju
from pytest_bdd import then

from tests.integration.helpers import (
    APP_NAME,
    GATEWAY_CONTAINER,
    GATEWAY_SERVICE,
    pebble_service_active,
)


@then("the envoy-gateway Pebble service is running")
def pebble_service_running(juju: Juju) -> None:
    """Assert the envoy-gateway Pebble service is active on unit 0."""
    unit = f"{APP_NAME}/0"
    assert pebble_service_active(juju, unit, GATEWAY_CONTAINER, GATEWAY_SERVICE)
