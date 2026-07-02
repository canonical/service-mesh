# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scaling steps for the envoy-ai-controller-k8s suite."""

from jubilant import Juju, all_active
from pytest_bdd import given, parsers, then, when

from tests.integration.helpers import APP_NAME, CONTAINER, SERVICE, pebble_service_active


@given(parsers.parse("the charm is scaled to {count:d} units"))
@given(parsers.parse("the charm is scaled to {count:d} unit"))
@when(parsers.parse("the charm is scaled to {count:d} units"))
@when(parsers.parse("the charm is scaled to {count:d} unit"))
def scale_to(juju: Juju, count: int) -> None:
    """Scale the application to ``count`` units."""
    juju.cli("scale-application", APP_NAME, str(count))


@given("all units reach active status")
@then("all units reach active status")
@when("all units reach active status")
def all_units_active(juju: Juju) -> None:
    """Wait until every unit of the charm settles into active status."""
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@then("the ai-gateway Pebble service is running on all units")
def pebble_running_all_units(juju: Juju) -> None:
    """Assert the ai-gateway Pebble service is active on every unit."""
    for unit in juju.status().apps[APP_NAME].units:
        assert pebble_service_active(juju, unit, CONTAINER, SERVICE)
