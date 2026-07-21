# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Extension server relation steps for the envoy-ai-controller-k8s suite."""

import json

from jubilant import Juju, all_active, all_agents_idle
from pytest_bdd import given, then, when

from tests.integration.helpers import (
    APP_NAME,
    ENVOY_CHANNEL,
    EXTENSION_SERVER_PORT,
    published_app_data,
)
from tests.integration.helpers import (
    CONTROLLER_APP as CONTROLLER,
)


def _decode(data: dict, key: str):
    """Return a databag value JSON-decoded (the interface serialises each field as JSON)."""
    raw = data.get(key)
    return json.loads(raw) if raw is not None else None


def _ext_server_related(juju: Juju) -> bool:
    """Return True if the charm's envoy-extension-server endpoint is related."""
    app = juju.status().apps.get(APP_NAME)
    rels = app.relations.get("envoy-extension-server", []) if app else []
    return any(r.related_app == CONTROLLER for r in rels)


@given("the envoy-controller-k8s charm is deployed")
def controller_deployed(juju: Juju) -> None:
    """Deploy the Envoy Gateway controller (extension-server requirer) from edge."""
    if CONTROLLER in juju.status().apps:
        return
    juju.deploy(CONTROLLER, channel=ENVOY_CHANNEL, trust=True)
    juju.wait(lambda s: all_active(s, CONTROLLER), timeout=1000, delay=5, successes=3)


@given("the envoy-extension-server relation is established with envoy-controller-k8s")
@when("the envoy-extension-server relation is established with envoy-controller-k8s")
def ext_server_relation_established(juju: Juju) -> None:
    """Relate the charm's envoy-extension-server endpoint to the controller.

    Idempotent: scenarios share a model, so the relation may already exist from a
    prior scenario.
    """
    if not _ext_server_related(juju):
        juju.integrate(f"{APP_NAME}:envoy-extension-server", CONTROLLER)
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME, CONTROLLER),
        timeout=1000,
        delay=5,
        successes=3,
    )


@then("the envoy-extension-server relation data contains the extension server fqdn")
def ext_server_fqdn_published(juju: Juju) -> None:
    """Assert the provider published its Extension Server FQDN to the controller."""
    data = published_app_data(juju, APP_NAME, CONTROLLER)
    fqdn = _decode(data, "extension_server_fqdn")
    assert fqdn and fqdn.startswith(APP_NAME)


@then("the envoy-extension-server relation data contains the extension server port")
def ext_server_port_published(juju: Juju) -> None:
    """Assert the provider published its Extension Server port to the controller."""
    data = published_app_data(juju, APP_NAME, CONTROLLER)
    assert str(_decode(data, "extension_server_port")) == str(EXTENSION_SERVER_PORT)


@then("the envoy-extension-server relation data contains the controller name")
def controller_name_received(juju: Juju) -> None:
    """Assert the requirer published its controller identity name back to the provider."""
    data = published_app_data(juju, CONTROLLER, APP_NAME)
    assert _decode(data, "controller_name")


@then("the envoy-extension-server relation data contains the controller namespace")
def controller_namespace_received(juju: Juju) -> None:
    """Assert the requirer published its namespace back to the provider."""
    data = published_app_data(juju, CONTROLLER, APP_NAME)
    assert _decode(data, "namespace")
