# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import scenario

import charm
from charm import EnvoyIngressCharm

CA_PEM = "CAPEM"
CERT_PEM = "CERTPEM"
KEY_PEM = "KEYPEM"


@pytest.fixture()
def ctx():
    return scenario.Context(EnvoyIngressCharm)


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Mock the charm's lightkube Client; trusted (list returns []) by default."""
    with patch("charm.Client") as client_cls:
        instance = client_cls.return_value
        instance.list.return_value = []
        yield instance


@pytest.fixture()
def gateway_class_accepted():
    """Patch the discovery probe so the controller is seen as available."""
    with patch.object(EnvoyIngressCharm, "_gateway_class_accepted", return_value=True):
        yield


@pytest.fixture()
def gateway_class_pending():
    """Patch the discovery probe so the controller is seen as unavailable."""
    with patch.object(EnvoyIngressCharm, "_gateway_class_accepted", return_value=False):
        yield


@pytest.fixture()
def certs_ready():
    """Patch the TLS lib so the charm sees an issued certificate + key."""
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
    """Replace the per-scope KRM factories with mocks.

    Yields a namespace exposing each resource manager mock so tests can assert
    on ``reconcile``/``delete`` calls without touching the cluster.
    """
    with patch.object(
        EnvoyIngressCharm, "_gateway_class_krm"
    ) as gateway_class, patch.object(
        EnvoyIngressCharm, "_gateway_krm"
    ) as gateway, patch.object(
        EnvoyIngressCharm, "_httproute_krm"
    ) as httproute, patch.object(
        EnvoyIngressCharm, "_security_policy_krm"
    ) as security_policy, patch.object(
        EnvoyIngressCharm, "_tls_secret_krm"
    ) as tls_secret:
        yield SimpleNamespace(
            gateway_class=gateway_class.return_value,
            gateway=gateway.return_value,
            httproute=httproute.return_value,
            security_policy=security_policy.return_value,
            tls_secret=tls_secret.return_value,
        )


def ingress_data(name: str, model: str, port: int = 8080):
    """Build a minimal stand-in for IngressRequirerData used by the charm."""
    return SimpleNamespace(app=SimpleNamespace(name=name, model=model, port=port))


def ready_ingress(*entries):
    """Patch _ready_ingress_data to return crafted (relation, data) tuples.

    Each entry is (app_name, model, port). The relation is a MagicMock whose
    ``app.name`` matches the requirer app name (used by conflict detection).
    """
    tuples = []
    for name, model, *rest in entries:
        port = rest[0] if rest else 8080
        relation = MagicMock()
        relation.app.name = name
        tuples.append((relation, ingress_data(name, model, port)))
    return patch.object(EnvoyIngressCharm, "_ready_ingress_data", return_value=tuples)


def make_state(
    *,
    certificates: bool = False,
    forward_auth: bool = False,
    gateway_metadata: bool = False,
    config: dict | None = None,
    planned_units: int = 1,
    leader: bool = True,
) -> scenario.State:
    """Build a State for the ingress charm with sensible defaults."""
    relations = set()
    if certificates:
        relations.add(scenario.Relation("certificates", interface="tls-certificates"))
    if forward_auth:
        relations.add(scenario.Relation("forward-auth", interface="forward_auth"))
    if gateway_metadata:
        relations.add(
            scenario.Relation("gateway-metadata", interface="gateway_metadata")
        )
    return scenario.State(
        leader=leader,
        planned_units=planned_units,
        relations=relations,
        config=config or {},
    )
