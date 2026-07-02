# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""GatewayClass / Gateway / EnvoyProxy resource steps for the envoy-ingress-k8s suite."""

from jubilant import Juju
from pytest_bdd import parsers, then

from tests.integration import helpers


@then(parsers.parse('a GatewayClass with controllerName "{controller}" exists'))
def gatewayclass_with_controller_exists(controller: str) -> None:
    """Assert the GatewayClass the charm references is present with the expected controller."""
    assert helpers.gateway_class_controller() == controller


@then("the GatewayClass has an Accepted condition set to True")
def gatewayclass_accepted() -> None:
    """Assert the controller has marked the GatewayClass Accepted=True."""
    assert helpers.gateway_class_accepted()


@then("a Gateway resource exists in the charm's namespace")
def gateway_exists(juju: Juju) -> None:
    """Assert the charm created its Gateway in the model namespace."""
    assert helpers.get_gateway(juju.model) is not None


@then("the Gateway has a Programmed condition set to True")
def gateway_programmed(juju: Juju) -> None:
    """Wait until Envoy Gateway marks the Gateway Programmed=True."""
    juju.wait(lambda _: helpers.gateway_programmed(juju.model), timeout=600, delay=5)


@then("an Envoy Proxy pod is running in the Gateway's namespace")
def envoy_proxy_pod_running(juju: Juju) -> None:
    """Assert Envoy Gateway provisioned a running proxy pod for the Gateway."""

    def _running(_) -> bool:
        pods = helpers.envoy_proxy_pods(juju.model)
        return any(p.status and p.status.phase == "Running" for p in pods)

    juju.wait(_running, timeout=600, delay=5)
