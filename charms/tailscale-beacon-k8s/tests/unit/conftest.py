# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import scenario

import charm
from charm import TailscaleBeaconCharm


@pytest.fixture()
def ctx():
    return scenario.Context(TailscaleBeaconCharm)


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Mock the charm's lightkube Client; trusted (list returns []) by default."""
    with patch("charm.Client") as client_cls:
        instance = client_cls.return_value
        instance.list.return_value = []
        yield instance


@pytest.fixture(autouse=True)
def no_sleep():
    """Neutralise the in-hook wait so tests do not actually block."""
    with patch("charm.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def ingress_io():
    """Stub the ingress provider's outbound calls (they emit events unfit for mocks).

    Yields a namespace exposing the publish_url / wipe_ingress_data mocks so tests
    can assert on them regardless of the (mock) relation objects passed in.
    """
    with patch.object(charm.IngressPerAppProvider, "publish_url") as publish, \
            patch.object(charm.IngressPerAppProvider, "wipe_ingress_data") as wipe:
        yield SimpleNamespace(publish_url=publish, wipe_ingress_data=wipe)


@pytest.fixture()
def service_krm_mock():
    """Replace the Service KRM factory with a mock to assert reconcile/delete calls."""
    with patch.object(TailscaleBeaconCharm, "_service_krm") as krm:
        yield krm.return_value


def proxy_state(hostname=None, pending=False, error=False, message=""):
    """Build a _ProxyState with sensible defaults."""
    return charm._ProxyState(
        hostname=hostname, pending=pending, error=error, message=message
    )


def ingress_data(name: str, model: str, port: int = 8080):
    """Build a minimal stand-in for IngressRequirerData used by the charm."""
    return SimpleNamespace(app=SimpleNamespace(name=name, model=model, port=port))


def ready_ingress(*entries):
    """Patch _ready_ingress_data to return crafted (relation, data) tuples.

    Each entry is (app_name, model[, port]). The relation is a MagicMock with a
    stable ``id`` and matching ``app.name``.
    """
    tuples = []
    for index, (name, model, *rest) in enumerate(entries):
        port = rest[0] if rest else 8080
        relation = MagicMock()
        relation.id = index
        relation.app.name = name
        tuples.append((relation, ingress_data(name, model, port)))
    return patch.object(TailscaleBeaconCharm, "_ready_ingress_data", return_value=tuples)


def proxy_states(**by_app):
    """Patch _proxy_state to return a canned _ProxyState keyed by app name."""

    def _fake(_self, app_name, _namespace):
        return by_app[app_name]

    return patch.object(TailscaleBeaconCharm, "_proxy_state", autospec=True, side_effect=_fake)


def make_state(
    *,
    ingress: int = 0,
    config: dict | None = None,
    planned_units: int = 1,
    leader: bool = True,
) -> scenario.State:
    """Build a State for the beacon charm with sensible defaults.

    ready-timeout defaults to 0 so the in-hook wait never actually blocks during
    unit tests (Scenario re-emits the event on manager exit); tests that exercise
    the wait pass an explicit value.
    """
    relations = {
        scenario.Relation("ingress", interface="ingress") for _ in range(ingress)
    }
    return scenario.State(
        leader=leader,
        planned_units=planned_units,
        relations=relations,
        config={"ready-timeout": 0, **(config or {})},
    )
