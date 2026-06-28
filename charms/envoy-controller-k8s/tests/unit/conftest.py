# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ops
import pytest
import scenario
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Secret

import charm
from charm import EnvoyControllerCharm

# Minimal plan so scenario's consistency checker accepts a 'readiness' check status
# on the input container (a CheckInfo requires the check to exist in the plan).
_GATEWAY_LAYER = ops.pebble.Layer(
    {
        "services": {"envoy-gateway": {"override": "replace", "command": "envoy-gateway"}},
        "checks": {
            "readiness": {
                "override": "replace",
                "level": "ready",
                "startup": "enabled",
                "threshold": 3,
            }
        },
    }
)

CA_PEM = "CAPEM"
CERT_PEM = "CERTPEM"
KEY_PEM = "KEYPEM"

# The certgen-issued control-plane Secret, as lightkube returns it: a TLS Secret
# named "envoy-gateway" whose data values are base64-encoded PEM (Secret wire format).
CONTROL_PLANE_SECRET = Secret(
    metadata=ObjectMeta(name=charm.CONTROL_PLANE_NAME),
    type="kubernetes.io/tls",
    data={
        "tls.crt": base64.b64encode(CERT_PEM.encode()).decode(),
        "tls.key": base64.b64encode(KEY_PEM.encode()).decode(),
        "ca.crt": base64.b64encode(CA_PEM.encode()).decode(),
    },
)


@pytest.fixture()
def ctx():
    return scenario.Context(EnvoyControllerCharm)


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Mock the charm's lightkube Client.

    Defaults: trusted (list returns []) and the certgen control-plane Secret present
    (get returns it), so reconcile reaches the cert push and Service steps.
    """
    with patch("charm.Client") as client_cls:
        instance = client_cls.return_value
        instance.list.return_value = []
        instance.get.return_value = CONTROL_PLANE_SECRET
        yield instance


@pytest.fixture()
def krm_mocks():
    """Replace the KRM factories with mocks and treat CRDs as Established.

    Yields a namespace with:
      - ``crd``: dict of scope -> KRM mock (populated as the charm calls _crd_krm)
      - ``webhook``: the webhook KRM mock
      - ``proxy``: the EnvoyProxy KRM mock
      - ``service``: the control-plane Service KRM mock
    """
    crd: dict = {}

    def crd_factory(scope):
        return crd.setdefault(scope, MagicMock())

    with patch.object(EnvoyControllerCharm, "_crd_krm", side_effect=crd_factory), patch.object(
        EnvoyControllerCharm, "_webhook_krm"
    ) as webhook, patch.object(EnvoyControllerCharm, "_envoy_proxy_krm") as proxy, patch.object(
        EnvoyControllerCharm, "_control_plane_service_krm"
    ) as service, patch.object(
        EnvoyControllerCharm, "_crds_established", return_value=True
    ):
        yield SimpleNamespace(
            crd=crd,
            webhook=webhook.return_value,
            proxy=proxy.return_value,
            service=service.return_value,
        )


def make_state(
    *,
    can_connect: bool = True,
    config: dict | None = None,
    gateway_checks=frozenset(),
    planned_units: int = 1,
    leader: bool = True,
    otlp_endpoint: str | None = None,
) -> scenario.State:
    """Build a State for the controller charm with sensible defaults."""
    relations = set()
    if otlp_endpoint:
        relations.add(
            scenario.Relation(
                "otlp",
                interface="otlp",
                remote_app_data={
                    "endpoints": json.dumps(
                        [
                            {
                                "endpoint": otlp_endpoint,
                                "protocol": "http",
                                "telemetries": ["metrics"],
                                "insecure": True,
                            }
                        ]
                    )
                },
            )
        )
    containers = {
        scenario.Container(
            "envoy-gateway",
            can_connect=can_connect,
            check_infos=gateway_checks,
            layers={"envoy-gateway": _GATEWAY_LAYER} if gateway_checks else {},
            execs={
                scenario.Exec(
                    ["envoy-gateway", "certgen", "--disable-topology-injector"],
                    return_code=0,
                )
            },
        ),
        scenario.Container("ai-gateway", can_connect=can_connect),
    }
    return scenario.State(
        leader=leader,
        planned_units=planned_units,
        relations=relations,
        containers=containers,
        config=config or {},
    )
