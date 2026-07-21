# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""OTLP relation steps for the envoy-controller-k8s suite."""

import json
from urllib.parse import urlparse

from jubilant import Juju, all_active, all_agents_idle
from pytest_bdd import given, then, when

from tests.integration.helpers import (
    APP_NAME,
    envoy_gateway_config,
    envoy_proxy_spec,
    published_app_data,
)

OTLP_COLLECTOR = "opentelemetry-collector-k8s"
OTLP_CHANNEL = "dev/edge"
TOPOLOGY_TAGS = {"juju_model", "juju_model_uuid", "juju_application", "juju_charm"}


def _config_sink(juju: Juju) -> dict | None:
    """Return the first Envoy Gateway telemetry metrics sink, or None."""
    sinks = envoy_gateway_config(juju).get("telemetry", {}).get("metrics", {}).get("sinks")
    return sinks[0] if sinks else None


def _proxy_sink(juju: Juju) -> dict | None:
    """Return the first EnvoyProxy telemetry metrics sink, or None."""
    sinks = envoy_proxy_spec(juju).get("telemetry", {}).get("metrics", {}).get("sinks")
    return sinks[0] if sinks else None


def _settled(s) -> bool:
    """Predicate: the controller has reconciled the OTLP relation.

    The collector charm stays blocked until it has a downstream output relation
    ("...for receive-otlp"), yet it still publishes its receive endpoints while
    blocked -- so we only require the controller to be workload-active. A unit
    reports "active" even while a hook is still running, so both agents must also
    be idle to know the relation-changed reconcile has finished.
    """
    return all_active(s, APP_NAME) and all_agents_idle(s, APP_NAME, OTLP_COLLECTOR)


def _collector_endpoint(juju: Juju) -> str:
    """Return the gRPC OTLP endpoint the collector publishes on its provider databag.

    The collector publishes both an HTTP (4318) and a gRPC (4317) endpoint; the
    charm requests ``grpc``, so the test matches against the gRPC one. The gRPC
    endpoint arrives as a bare ``host:port`` (no scheme).
    """
    endpoints = published_app_data(juju, OTLP_COLLECTOR, APP_NAME).get("endpoints")
    assert endpoints, "collector published no OTLP endpoints"
    grpc = [e["endpoint"] for e in json.loads(endpoints) if e["protocol"] == "grpc"]
    assert grpc, "collector published no gRPC OTLP endpoint"
    return grpc[0]


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


@then("no OTLP sink is configured in the Envoy Gateway config")
def no_config_sink(juju: Juju) -> None:
    """Assert the Envoy Gateway config carries no telemetry sink."""
    assert _config_sink(juju) is None


@then("no OTLP sink is configured in the default EnvoyProxy resource")
def no_proxy_sink(juju: Juju) -> None:
    """Assert the default EnvoyProxy carries no telemetry sink."""
    assert _proxy_sink(juju) is None


@then("the Envoy Gateway config contains a telemetry.metrics.sinks entry")
def config_has_sink(juju: Juju) -> None:
    """Assert the Envoy Gateway config carries a telemetry sink."""
    assert _config_sink(juju) is not None


@then("the default EnvoyProxy resource contains a telemetry.metrics.sinks entry")
def proxy_has_sink(juju: Juju) -> None:
    """Assert the default EnvoyProxy carries a telemetry sink."""
    assert _proxy_sink(juju) is not None


@then("the sink type is OpenTelemetry")
def sink_type_opentelemetry(juju: Juju) -> None:
    """Assert both sinks are of type OpenTelemetry."""
    assert _config_sink(juju)["type"] == "OpenTelemetry"
    assert _proxy_sink(juju)["type"] == "OpenTelemetry"


@then("the sink host and port match the OTLP relation data")
def sink_host_port_match(juju: Juju) -> None:
    """Assert the config sink host/port match the collector's published endpoint."""
    endpoint = _collector_endpoint(juju)
    parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
    sink = _config_sink(juju)["openTelemetry"]
    assert sink["host"] == parsed.hostname
    assert sink["port"] == (parsed.port or 4317)


@then("the default EnvoyProxy resource stamps Juju topology stats tags on proxy metrics")
def proxy_topology_tags(juju: Juju) -> None:
    """Assert the EnvoyProxy bootstrap patches carry the Juju topology stats tags."""
    patches = envoy_proxy_spec(juju)["bootstrap"]["jsonPatches"]
    tag_names = {p["value"]["tag_name"] for p in patches}
    assert TOPOLOGY_TAGS <= tag_names


@then("the otlp relation data contains alert rules")
def otlp_alert_rules(juju: Juju) -> None:
    """Assert the charm published alert rules onto the otlp requirer databag."""
    data = published_app_data(juju, APP_NAME, OTLP_COLLECTOR)
    assert data.get("rules")
