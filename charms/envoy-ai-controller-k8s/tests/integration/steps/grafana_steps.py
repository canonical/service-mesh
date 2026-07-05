# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Grafana dashboard relation steps for the envoy-ai-controller-k8s suite."""

import base64
import json
import lzma

from jubilant import Juju, all_active, all_agents_idle
from pytest_bdd import given, then, when

from tests.integration.helpers import APP_NAME, published_app_data

GRAFANA = "grafana"
GRAFANA_CHANNEL = "dev/edge"
LLM_DASHBOARD = "Envoy AI Gateway - LLM Consumption"


def _dashboard_titles(juju: Juju) -> set[str]:
    """Decode the grafana-dashboard databag and return the dashboard titles."""
    data = published_app_data(juju, APP_NAME, GRAFANA)
    templates = json.loads(data["dashboards"])["templates"]
    titles = set()
    for tmpl in templates.values():
        raw = lzma.decompress(base64.b64decode(tmpl["content"]))
        titles.add(json.loads(raw)["title"])
    return titles


@given("the grafana-k8s charm is deployed")
def grafana_deployed(juju: Juju) -> None:
    """Deploy grafana-k8s if it is not already present."""
    if GRAFANA in juju.status().apps:
        return
    juju.deploy("grafana-k8s", app=GRAFANA, channel=GRAFANA_CHANNEL, trust=True)
    juju.wait(lambda s: all_active(s, GRAFANA), timeout=1000, delay=5, successes=3)


@when("the grafana-dashboard relation is established with grafana-k8s")
def grafana_relation_established(juju: Juju) -> None:
    """Relate the charm's grafana-dashboard endpoint to grafana and wait to settle."""
    juju.integrate(f"{APP_NAME}:grafana-dashboard", GRAFANA)
    juju.wait(
        lambda s: all_active(s, APP_NAME, GRAFANA) and all_agents_idle(s, APP_NAME, GRAFANA),
        timeout=1000,
        delay=5,
        successes=3,
    )


@then("the grafana-dashboard relation data contains dashboard JSON")
def dashboard_data_present(juju: Juju) -> None:
    """Assert the charm published dashboard content onto the databag."""
    assert _dashboard_titles(juju)


@then("the dashboard JSON includes an LLM consumption dashboard")
def llm_dashboard_present(juju: Juju) -> None:
    """Assert the LLM consumption dashboard is published."""
    assert LLM_DASHBOARD in _dashboard_titles(juju)
