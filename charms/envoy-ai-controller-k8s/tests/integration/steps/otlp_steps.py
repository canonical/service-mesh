# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""OTLP relation steps for the envoy-ai-controller-k8s suite."""

import json

import yaml
from jubilant import Juju, all_active, all_agents_idle
from pytest_bdd import given, then, when

from tests.integration.helpers import (
    APP_NAME,
    CONTAINER,
    SERVICE,
    _pebble,
    published_app_data,
)

OTLP_COLLECTOR = "opentelemetry-collector-k8s"
OTLP_CHANNEL = "dev/edge"

# The pebble-layer arg the charm derives from the otlp relation; its value is what
# switches OTLP export on in every injected ExtProc sidecar.
EXTPROC_OTLP_ARG = "--extProcExtraEnvVars=OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="


def _controller_command(juju: Juju) -> str:
    """Return the controller service command from the workload's pebble plan."""
    out = juju.cli("exec", "--unit", f"{APP_NAME}/0", "--", _pebble(CONTAINER, "plan"))
    return yaml.safe_load(out)["services"][SERVICE]["command"]


def _settled(s) -> bool:
    """Predicate: the controller has reconciled the OTLP relation.

    The collector charm stays blocked until it has a downstream output relation,
    yet it still publishes its receive endpoints while blocked -- so we only
    require the controller to be workload-active. A unit reports "active" even
    while a hook is still running, so both agents must also be idle to know the
    relation-changed reconcile has finished.
    """
    return all_active(s, APP_NAME) and all_agents_idle(s, APP_NAME, OTLP_COLLECTOR)


def _collector_http_endpoint(juju: Juju) -> str:
    """Return the HTTP OTLP endpoint URL the collector publishes on its databag."""
    endpoints = published_app_data(juju, OTLP_COLLECTOR, APP_NAME).get("endpoints")
    assert endpoints, "collector published no OTLP endpoints"
    http = [e["endpoint"] for e in json.loads(endpoints) if e["protocol"] == "http"]
    assert http, "collector published no HTTP OTLP endpoint"
    return http[0]


def _otlp_related(juju: Juju) -> bool:
    """Return True if the charm's otlp endpoint is already related to the collector."""
    app = juju.status().apps.get(APP_NAME)
    rels = app.relations.get("otlp", []) if app else []
    return any(r.related_app == OTLP_COLLECTOR for r in rels)


@given("the opentelemetry-collector charm is deployed")
def collector_deployed(juju: Juju) -> None:
    """Deploy the OTLP collector if it is not already present.

    The collector stays blocked until it has a downstream output relation, so we
    wait for its agent to go idle (deployed and settled) rather than for active.
    """
    if OTLP_COLLECTOR in juju.status().apps:
        return
    juju.deploy(OTLP_COLLECTOR, channel=OTLP_CHANNEL, trust=True)
    juju.wait(lambda s: all_agents_idle(s, OTLP_COLLECTOR), timeout=1000, delay=5, successes=3)


@given("the otlp relation is established with opentelemetry-collector")
@when("the otlp relation is established with opentelemetry-collector")
def otlp_relation_established(juju: Juju) -> None:
    """Relate the charm's otlp endpoint to the collector and wait for it to settle.

    Idempotent: scenarios share a model, so the relation may already exist from a
    prior scenario.
    """
    if not _otlp_related(juju):
        juju.integrate(f"{APP_NAME}:otlp", OTLP_COLLECTOR)
    juju.wait(_settled, timeout=1000, delay=5, successes=3)


@when("the otlp relation is removed")
def otlp_relation_removed(juju: Juju) -> None:
    """Remove the otlp relation and wait for the charm to settle."""
    juju.remove_relation(f"{APP_NAME}:otlp", OTLP_COLLECTOR)
    juju.wait(_settled, timeout=1000, delay=5, successes=3)


@then("the controller command carries no ExtProc OTLP environment")
def no_extproc_otlp_env(juju: Juju) -> None:
    """Assert the pebble command carries no ExtProc OTLP env var injection."""
    assert EXTPROC_OTLP_ARG not in _controller_command(juju)


@then("the controller command sets the ExtProc OTLP metrics endpoint")
def extproc_otlp_env_set(juju: Juju) -> None:
    """Assert the pebble command injects the OTLP metrics endpoint into ExtProcs."""
    assert EXTPROC_OTLP_ARG in _controller_command(juju)


@then("the ExtProc OTLP metrics endpoint matches the OTLP relation data")
def extproc_otlp_env_matches(juju: Juju) -> None:
    """Assert the injected endpoint is the collector's HTTP URL plus /v1/metrics."""
    expected = _collector_http_endpoint(juju).rstrip("/") + "/v1/metrics"
    assert f"{EXTPROC_OTLP_ARG}{expected}" in _controller_command(juju)


@then("the otlp relation data contains alert rules")
def otlp_alert_rules(juju: Juju) -> None:
    """Assert the charm published alert rules onto the otlp requirer databag."""
    data = published_app_data(juju, APP_NAME, OTLP_COLLECTOR)
    assert data.get("rules")
