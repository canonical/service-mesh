# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ops
import pytest
import scenario

import charm
from charm import EnvoyAiControllerCharm

CA_PEM = "CAPEM"
CERT_PEM = "CERTPEM"
KEY_PEM = "KEYPEM"

# Minimal plan so scenario's consistency checker accepts a 'readiness' check status
# on the input container (a CheckInfo requires the check to exist in the plan).
_CONTROLLER_LAYER = ops.pebble.Layer(
    {
        "services": {"ai-gateway": {"override": "replace", "command": "/app"}},
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


@pytest.fixture()
def ctx():
    return scenario.Context(EnvoyAiControllerCharm)


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Mock the charm's lightkube Client; trusted (list returns []) by default."""
    with patch("charm.Client") as client_cls:
        instance = client_cls.return_value
        instance.list.return_value = []
        yield instance


@pytest.fixture(autouse=True)
def certs_ready():
    """Patch the TLS lib so the charm sees an issued certificate + key by default.

    Tests that need the no-cert path override this via the ``certs_absent`` fixture.
    """
    cert = SimpleNamespace(certificate=CERT_PEM, ca=CA_PEM)
    with patch.object(
        charm.TLSCertificatesRequiresV4,
        "get_assigned_certificates",
        return_value=([cert], KEY_PEM),
    ):
        yield


@pytest.fixture()
def certs_absent():
    """Patch the TLS lib so the charm sees no issued certificate."""
    with patch.object(
        charm.TLSCertificatesRequiresV4,
        "get_assigned_certificates",
        return_value=([], None),
    ):
        yield


@pytest.fixture()
def krm_mocks():
    """Replace the KRM factories with mocks and treat CRDs as Established.

    Yields a namespace with:
      - ``crd``: dict of scope -> KRM mock (populated as the charm calls _crd_krm)
      - ``webhook``: the ExtProc MutatingWebhookConfiguration KRM mock
    """
    crd: dict = {}

    def crd_factory(scope):
        return crd.setdefault(scope, MagicMock())

    with patch.object(
        EnvoyAiControllerCharm, "_crd_krm", side_effect=crd_factory
    ), patch.object(EnvoyAiControllerCharm, "_webhook_krm") as webhook, patch.object(
        EnvoyAiControllerCharm, "_crds_established", return_value=True
    ):
        yield SimpleNamespace(
            crd=crd,
            webhook=webhook.return_value,
        )


def make_state(
    *,
    can_connect: bool = True,
    config: dict | None = None,
    certificates: bool = True,
    extension_server: bool = True,
    controller_checks=frozenset(),
    planned_units: int = 1,
    leader: bool = True,
) -> scenario.State:
    """Build a State for the AI controller charm with sensible defaults."""
    relations = set()
    if certificates:
        relations.add(scenario.Relation("certificates", interface="tls-certificates"))
    if extension_server:
        relations.add(
            scenario.Relation(
                "envoy-extension-server", interface="envoy_extension_server"
            )
        )
    containers = {
        scenario.Container(
            "ai-gateway",
            can_connect=can_connect,
            check_infos=controller_checks,
            layers={"ai-gateway": _CONTROLLER_LAYER} if controller_checks else {},
        ),
    }
    return scenario.State(
        leader=leader,
        planned_units=planned_units,
        relations=relations,
        containers=containers,
        config=config or {},
    )
