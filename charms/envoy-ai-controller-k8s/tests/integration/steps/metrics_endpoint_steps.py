# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""metrics-endpoint (prometheus_scrape) relation steps for envoy-ai-controller-k8s."""

import json

from jubilant import Juju, all_agents_idle
from pytest_bdd import given, then, when

from tests.integration.helpers import APP_NAME, published_app_data

# Reuse the OTelCol from otlp_steps as the metrics-endpoint requirer — its
# `metrics-endpoint: prometheus_scrape` requires slot is exactly what we
# provide. Keeping the constant local so this file does not depend on the
# otlp step module's internals.
OTLP_COLLECTOR = "opentelemetry-collector-k8s"
METRICS_PORT = 8080


def _metrics_endpoint_related(juju: Juju) -> bool:
    """Return True if the charm's metrics-endpoint is already related to the collector."""
    app = juju.status().apps.get(APP_NAME)
    rels = app.relations.get("metrics-endpoint", []) if app else []
    return any(r.related_app == OTLP_COLLECTOR for r in rels)


def _scrape_targets(juju: Juju) -> list[str]:
    """Return every target host:port advertised on the metrics-endpoint databag."""
    raw = published_app_data(juju, APP_NAME, OTLP_COLLECTOR).get("scrape_jobs")
    if not raw:
        return []
    targets: list[str] = []
    for job in json.loads(raw):
        for cfg in job.get("static_configs", []):
            targets.extend(cfg.get("targets", []))
    return targets


@given("the metrics-endpoint relation is established with opentelemetry-collector")
@when("the metrics-endpoint relation is established with opentelemetry-collector")
def metrics_endpoint_relation_established(juju: Juju) -> None:
    """Relate the charm's metrics-endpoint to the collector and wait for both to settle."""
    if not _metrics_endpoint_related(juju):
        juju.integrate(f"{APP_NAME}:metrics-endpoint", OTLP_COLLECTOR)
    juju.wait(
        lambda s: all_agents_idle(s, APP_NAME, OTLP_COLLECTOR),
        timeout=1000,
        delay=5,
        successes=3,
    )


@then("the metrics-endpoint relation data advertises the controller port")
def metrics_endpoint_advertises_port(juju: Juju) -> None:
    """Assert the scrape_jobs databag entry names the controller's metrics port."""
    targets = _scrape_targets(juju)
    assert any(t.endswith(f":{METRICS_PORT}") for t in targets), (
        f"expected a target ending in :{METRICS_PORT}, got {targets!r}"
    )


@then("the metrics-endpoint relation data ships alert rules")
def metrics_endpoint_ships_alert_rules(juju: Juju) -> None:
    """Assert the charm published alert rules onto the metrics-endpoint databag."""
    data = published_app_data(juju, APP_NAME, OTLP_COLLECTOR)
    assert data.get("alert_rules"), "expected alert_rules to be published"
