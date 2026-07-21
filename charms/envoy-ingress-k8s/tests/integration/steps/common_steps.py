# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared model/deploy/status steps for the envoy-ingress-k8s suite."""

from pathlib import Path

from jubilant import Juju, all_active, all_blocked, all_waiting
from pytest_bdd import given, parsers, then, when

from tests.integration.helpers import APP_NAME, CONTROLLER_APP, CONTROLLER_CHANNEL


@given("a Juju Kubernetes model")
def a_juju_kubernetes_model(juju: Juju) -> None:
    """The module-scoped Juju model provided by pytest-jubilant."""


@given("the envoy-controller-k8s charm is deployed with trust and active")
def controller_deployed_and_active(juju: Juju) -> None:
    """Deploy the control-plane controller from charmhub and wait for it to go active."""
    if CONTROLLER_APP not in juju.status().apps:
        juju.deploy(CONTROLLER_APP, channel=CONTROLLER_CHANNEL, trust=True)
    juju.wait(lambda s: all_active(s, CONTROLLER_APP), timeout=1000, delay=5, successes=3)


@given("the envoy-ingress-k8s charm is deployed with trust")
@when("the envoy-ingress-k8s charm is deployed with trust")
def deployed_with_trust(juju: Juju, charm: Path, resources: dict) -> None:
    """Deploy the charm with --trust, or grant trust if already deployed untrusted."""
    if APP_NAME in juju.status().apps:
        juju.trust(APP_NAME, scope="cluster")
        return
    juju.deploy(charm, resources=resources, app=APP_NAME, trust=True)


@given("the envoy-ingress-k8s charm is deployed with trust and active")
def deployed_with_trust_and_active(juju: Juju, charm: Path, resources: dict) -> None:
    """Deploy the charm with --trust and wait for it to reach active status."""
    if APP_NAME not in juju.status().apps:
        juju.deploy(charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@when("the envoy-ingress-k8s charm is deployed without trust")
def deployed_without_trust(juju: Juju, charm: Path, resources: dict) -> None:
    """Deploy the charm without --trust to observe the blocked, untrusted state."""
    if APP_NAME in juju.status().apps:
        return
    juju.deploy(charm, resources=resources, app=APP_NAME, trust=False)


@given("the charm reaches active status")
@when("the charm reaches active status")
@then("the charm reaches active status")
def charm_reaches_active(juju: Juju) -> None:
    """Wait until the charm settles into active status."""
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@then("the charm is active")
def charm_is_active(juju: Juju) -> None:
    """Assert the charm is currently active."""
    assert all_active(juju.status(), APP_NAME)


@then(parsers.parse('the charm is waiting with message "{message}"'))
def charm_is_waiting_with_message(juju: Juju, message: str) -> None:
    """Wait until the charm settles into waiting with the expected message."""
    juju.wait(
        lambda s: all_waiting(s, APP_NAME)
        and s.apps[APP_NAME].app_status.message == message,
        timeout=1000,
        delay=5,
        successes=3,
    )


@then(parsers.parse('the charm is blocked with message "{message}"'))
def charm_is_blocked_with_message(juju: Juju, message: str) -> None:
    """Wait until the charm settles into blocked with the expected message."""
    juju.wait(
        lambda s: all_blocked(s, APP_NAME)
        and s.apps[APP_NAME].app_status.message == message,
        timeout=1000,
        delay=5,
        successes=3,
    )
