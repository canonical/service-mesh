#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""Tests for charm tracing over the `charm-tracing` relation."""

import json
from unittest.mock import patch

from scenario import Relation, State

CHARM_TRACING_RELATION = "charm-tracing"
TRACING_ENDPOINT = "http://tempo.example.com:4318"


def test_charm_tracing_requests_otlp_http(istio_beacon_context):
    """The charm requests the otlp_http protocol on the charm-tracing relation."""
    relation = Relation(CHARM_TRACING_RELATION, interface="tracing")
    state_out = istio_beacon_context.run(
        istio_beacon_context.on.relation_joined(relation),
        State(leader=True, relations=[relation]),
    )
    requested = json.loads(state_out.get_relation(relation.id).local_app_data["receivers"])
    assert requested == ["otlp_http"]


def test_charm_tracing_sets_destination_from_relation(istio_beacon_context):
    """When the relation provides an otlp_http endpoint, tracing is pointed at it."""
    relation = Relation(
        CHARM_TRACING_RELATION,
        interface="tracing",
        remote_app_data={
            "receivers": json.dumps(
                [
                    {
                        "protocol": {"name": "otlp_http", "type": "http"},
                        "url": TRACING_ENDPOINT,
                    }
                ]
            )
        },
        local_app_data={"receivers": json.dumps(["otlp_http"])},
    )
    with patch("ops.tracing.set_destination") as mock_set_destination:
        istio_beacon_context.run(
            istio_beacon_context.on.relation_changed(relation),
            State(leader=True, relations=[relation]),
        )
    mock_set_destination.assert_called_with(url=f"{TRACING_ENDPOINT}/v1/traces", ca=None)


def test_charm_tracing_clears_destination_without_relation(istio_beacon_context):
    """With no charm-tracing relation, the tracing destination is cleared."""
    with patch("ops.tracing.set_destination") as mock_set_destination:
        istio_beacon_context.run(
            istio_beacon_context.on.start(),
            State(leader=True, relations=[]),
        )
    mock_set_destination.assert_called_with(url=None, ca=None)


def test_charm_tracing_emits_spans(istio_beacon_context):
    """Handling an event actually emits OpenTelemetry spans attributed to this charm."""
    istio_beacon_context.run(
        istio_beacon_context.on.update_status(),
        State(leader=True, relations=[]),
    )

    spans = istio_beacon_context.trace_data
    # Spans were actually produced and buffered by ops[tracing].
    assert spans, "expected the charm to emit trace spans"
    # The dispatch is captured under a root span, with child spans nested under it.
    assert "ops.main" in {span.name for span in spans}
    assert len(spans) > 1
    # The spans are attributed to this charm.
    resource_attributes = spans[0].resource.attributes
    assert resource_attributes["charm"] == "istio-beacon-k8s"
    assert resource_attributes["charm_type"] == "IstioBeaconCharm"
