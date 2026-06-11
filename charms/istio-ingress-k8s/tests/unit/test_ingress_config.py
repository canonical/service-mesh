from textwrap import dedent

import pytest
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppRequirer,
)
from ops.charm import CharmBase
from ops.testing import Harness


def dequote(s: str):
    if isinstance(s, str) and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s


class MockRequirerCharm(CharmBase):
    META = dedent(
        """\
        name: test-requirer
        requires:
          ingress:
            interface: ingress
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipa = IngressPerAppRequirer(self, port=80, strip_prefix=True, host="foo.bar")


@pytest.fixture()
def harness():
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness.set_model_name("test_ingress")
    harness.begin()
    yield harness
    harness.cleanup()


def test_config_changed(harness: Harness[MockRequirerCharm]):
    harness.set_leader(True)
    harness.add_network("10.0.0.10")
    relation_id = harness.add_relation("ingress", "istio-ingress")
    harness.add_relation_unit(relation_id, "istio-ingress/0")

    req_app_data = harness.get_relation_data(relation_id, "test-requirer")
    req_unit_data = harness.get_relation_data(relation_id, "test-requirer/0")

    assert dequote(req_app_data["name"]) == "test-requirer"
    assert dequote(req_app_data["port"]) == "80"
    assert dequote(req_app_data["strip-prefix"]) == "true"
    assert dequote(req_unit_data["host"]) == "foo.bar"
