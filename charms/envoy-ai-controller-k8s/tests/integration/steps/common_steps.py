# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared model/deploy/status steps for the envoy-ai-controller-k8s suite."""

from pathlib import Path

from jubilant import Juju, all_active, all_blocked
from pytest_bdd import given, parsers, then, when

from tests.integration.helpers import APP_NAME


@given("a Juju Kubernetes model")
def a_juju_kubernetes_model(juju: Juju) -> None:
    """The module-scoped Juju model provided by pytest-jubilant."""


@given("the envoy-ai-controller-k8s charm is deployed with trust")
@when("the envoy-ai-controller-k8s charm is deployed with trust")
def deployed_with_trust(juju: Juju, charm: Path, resources: dict) -> None:
    """Deploy the charm with --trust, or grant trust if already deployed untrusted."""
    if APP_NAME in juju.status().apps:
        juju.trust(APP_NAME, scope="cluster")
        return
    juju.deploy(charm, resources=resources, app=APP_NAME, trust=True)


@when("the envoy-ai-controller-k8s charm is deployed without trust")
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


@then(parsers.parse('the charm is blocked with message "{message}"'))
def charm_is_blocked_with_message(juju: Juju, message: str) -> None:
    """Wait for blocked status and assert the workload message matches."""
    juju.wait(lambda s: all_blocked(s, APP_NAME), timeout=1000, delay=5, successes=3)
    status = juju.status()
    assert status.apps[APP_NAME].app_status.message == message
