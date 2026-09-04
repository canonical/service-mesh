# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests ensuring every provides/requires relation is exercised except for tracing.

Provides:
  * ingress                              -> test_charm_ipa.py::test_relate
  * ingress-unauthenticated              -> covered HERE (test_ingress_unauthenticated)
  * metrics-endpoint                     -> covered HERE (test_metrics_endpoint)
  * istio-ingress-config                 -> test_charm_auth.py::test_relations_setup
  * istio-ingress-route                  -> test_charm_istio_ingress_route.py::test_relate_tester_http
  * istio-ingress-route-unauthenticated  -> covered HERE (test_istio_ingress_route_unauthenticated)
  * gateway-metadata                     -> test_gateway_metadata.py::test_relate_gateway_metadata
  * istio-request-auth                   -> test_charm_request_auth.py::test_malformed_relate_without_data

Requires:
  * certificates                         -> test_charm_istio_ingress_route.py::test_relate_certificates
  * charm-tracing                        -> intentionally skipped
  * forward-auth                         -> test_charm_auth.py::test_relations_setup
  * upstream-ingress                     -> test_upstream_ingress.py::test_relate
"""

import logging
from pathlib import Path

import pytest
import yaml
from jubilant import Juju, all_active, all_agents_idle

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]

# Requirer of the `ingress` interface, related on the provider's
# `ingress-unauthenticated` endpoint.
IPA_TESTER_UNAUTH = "ipa-tester-unauth"
# Requirer of the `istio_ingress_route` interface, related on the provider's
# `istio-ingress-route-unauthenticated` endpoint.
ROUTE_TESTER = "route-tester"
# Real charm requiring `metrics-endpoint` (prometheus_scrape).
PROMETHEUS = "prometheus-k8s"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy_dependencies")
def test_deploy_dependencies(juju: Juju, istio_core_juju: Juju, tester_http_charm):
    """Deploy the requirer charms used to exercise the provider relations."""
    # istio_core_juju fixture deploys istio-k8s in a separate model.
    juju.deploy(
        tester_http_charm,
        app=IPA_TESTER_UNAUTH,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.deploy(
        tester_http_charm,
        app=ROUTE_TESTER,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.deploy(PROMETHEUS, channel="3.11/edge", trust=True)
    juju.wait(
        lambda s: all_active(s, IPA_TESTER_UNAUTH, ROUTE_TESTER, PROMETHEUS)
        and all_agents_idle(s, IPA_TESTER_UNAUTH, ROUTE_TESTER, PROMETHEUS),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_deployment", depends=["test_deploy_dependencies"])
def test_deployment(juju: Juju, istio_ingress_charm, resources):
    """Deploy istio-ingress-k8s."""
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(
        lambda s: all_active(s, APP_NAME) and all_agents_idle(s, APP_NAME),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_ingress_unauthenticated", depends=["test_deployment"])
def test_ingress_unauthenticated(juju: Juju):
    """Relate a requirer on the `ingress-unauthenticated` provider endpoint."""
    juju.integrate(f"{IPA_TESTER_UNAUTH}:ingress", f"{APP_NAME}:ingress-unauthenticated")
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER_UNAUTH)
        and all_agents_idle(s, APP_NAME, IPA_TESTER_UNAUTH),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(
    name="test_istio_ingress_route_unauthenticated", depends=["test_deployment"]
)
def test_istio_ingress_route_unauthenticated(juju: Juju):
    """Relate a requirer on the `istio-ingress-route-unauthenticated` provider endpoint."""
    juju.integrate(
        f"{ROUTE_TESTER}:istio-ingress-route",
        f"{APP_NAME}:istio-ingress-route-unauthenticated",
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, ROUTE_TESTER)
        and all_agents_idle(s, APP_NAME, ROUTE_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_metrics_endpoint", depends=["test_deployment"])
def test_metrics_endpoint(juju: Juju):
    """Relate prometheus-k8s on the `metrics-endpoint` provider endpoint."""
    juju.integrate(f"{PROMETHEUS}:metrics-endpoint", f"{APP_NAME}:metrics-endpoint")
    juju.wait(
        lambda s: all_active(s, APP_NAME, PROMETHEUS)
        and all_agents_idle(s, APP_NAME, PROMETHEUS),
        timeout=1000,
        delay=5,
        successes=3,
    )
