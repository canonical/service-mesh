# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the upstream-ingress chaining feature."""

from unittest.mock import PropertyMock, patch

import pytest
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import IstioIngressCharm


@pytest.fixture()
def harness():
    harness = Harness(IstioIngressCharm)
    harness.set_model_name("istio-system")
    yield harness
    harness.cleanup()


def test_ingress_url_cascades_through_upstream(harness):
    """When upstream ingress is ready, _ingress_url returns the upstream URL with scheme stripped."""
    harness.begin()
    charm = harness.charm
    charm._ingress_url_ = None

    with patch.object(
        charm.upstream_ingress, "is_ready", return_value=True
    ), patch.object(
        IngressPerAppRequirer, "url", new_callable=PropertyMock, return_value="https://upstream.example.com/model-app/"
    ):
        assert charm._ingress_url == "upstream.example.com/model-app"


def test_ingress_url_falls_back_without_upstream(harness):
    """Without upstream, _ingress_url returns external_hostname or LB address."""
    harness.begin()
    charm = harness.charm
    charm._ingress_url_ = None

    with patch.object(
        charm.upstream_ingress, "is_ready", return_value=False
    ), patch(
        "charm.IstioIngressCharm._get_lb_external_address",
        new_callable=PropertyMock,
        return_value="10.1.1.1",
    ):
        assert charm._ingress_url == "10.1.1.1"


def test_ingress_url_with_scheme_uses_upstream(harness):
    """_ingress_url_with_scheme returns the full cascaded URL including the upstream's scheme."""
    harness.begin()
    charm = harness.charm
    charm._ingress_url_ = None

    with patch.object(
        charm.upstream_ingress, "is_ready", return_value=True
    ), patch.object(
        IngressPerAppRequirer, "url", new_callable=PropertyMock, return_value="https://upstream.example.com/model-app/"
    ):
        assert charm._ingress_url_with_scheme() == "https://upstream.example.com/model-app"


def test_construct_gateway_uses_local_address_not_upstream(harness):
    """The Gateway K8s resource hostname should use the local address, not the cascaded upstream."""
    harness.update_config({"external_hostname": "local.example.com"})
    harness.begin()
    charm = harness.charm

    with patch.object(
        charm.upstream_ingress, "is_ready", return_value=True
    ), patch.object(
        IngressPerAppRequirer, "url", new_callable=PropertyMock, return_value="https://upstream.example.com/model-app/"
    ):
        listeners = [{"port": 80, "gateway_protocol": "HTTP", "tls_secret_name": None, "source_app": "test"}]
        gateway = charm._construct_gateway(listeners)
        assert gateway.spec["listeners"][0]["hostname"] == "local.example.com"
