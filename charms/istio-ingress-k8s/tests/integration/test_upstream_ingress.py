# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for upstream ingress chaining with traefik-k8s."""

import logging
from pathlib import Path

import pytest
import yaml
from conftest import get_relation_data
from helpers import (
    get_ca_certificate,
    get_k8s_service_address,
    send_http_request,
    send_http_request_with_custom_ca,
)
from jubilant import Juju, all_active, all_agents_idle

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
TRAEFIK_APP = "traefik-k8s"
IPA_TESTER = "ipa-tester"
SELF_SIGNED_CERTS = "self-signed-certificates"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy")
def test_deploy(juju: Juju, istio_core_juju: Juju, istio_ingress_charm, resources, tester_http_charm):
    """Deploy istio-ingress, traefik (upstream), and tester charms."""
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.deploy(TRAEFIK_APP, channel="latest/edge", trust=True)
    juju.deploy(
        tester_http_charm,
        app=IPA_TESTER,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.wait(
        lambda s: all_active(s, APP_NAME, TRAEFIK_APP, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_relate", depends=["test_deploy"])
def test_relate(juju: Juju):
    """Relate tester to istio-ingress and istio-ingress to traefik upstream."""
    juju.integrate(f"{IPA_TESTER}:ingress", f"{APP_NAME}:ingress")
    juju.integrate(f"{APP_NAME}:upstream-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(
        lambda s: all_active(s, APP_NAME, TRAEFIK_APP, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_http_through_upstream", depends=["test_relate"])
def test_http_through_upstream(juju: Juju):
    """Test HTTP connectivity through the traefik -> istio chain."""
    data = get_relation_data(
        requirer_endpoint=f"{IPA_TESTER}/0:ingress",
        provider_endpoint=f"{APP_NAME}/0:ingress",
        model=juju.model,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    url = provider_app_data["url"]

    # Verify URL is cascaded through upstream (not pointing at istio's local LB)
    istio_address = get_k8s_service_address(juju.model, f"{APP_NAME}-istio")
    assert istio_address not in url, (
        f"Expected cascaded URL through upstream, not direct istio address: {url}"
    )

    assert send_http_request(url), f"Failed to reach tester through upstream chain: {url}"


@pytest.mark.dependency(name="test_add_tls", depends=["test_http_through_upstream"])
def test_add_tls(juju: Juju):
    """Add TLS to both istio-ingress and traefik via self-signed-certificates."""
    juju.deploy(SELF_SIGNED_CERTS)
    juju.wait(
        lambda s: all_active(s, SELF_SIGNED_CERTS),
        timeout=1000,
        delay=5,
        successes=3,
    )
    juju.integrate(f"{SELF_SIGNED_CERTS}:certificates", f"{APP_NAME}:certificates")
    juju.integrate(f"{SELF_SIGNED_CERTS}:certificates", f"{TRAEFIK_APP}:certificates")
    # Wait for all apps active AND all unit agents idle. After TLS integration there's
    # a cascade: certs issued → traefik updates URL to https → istio-ingress picks up
    # new URL → republishes to downstream apps.  all_active alone only checks workload
    # status (stays "active" throughout), so we also need all_agents_idle to ensure
    # no hooks are still executing.
    juju.wait(
        lambda s: all_active(s, APP_NAME, TRAEFIK_APP, SELF_SIGNED_CERTS, IPA_TESTER)
        and all_agents_idle(s, APP_NAME, TRAEFIK_APP, SELF_SIGNED_CERTS, IPA_TESTER),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_https_through_upstream", depends=["test_add_tls"])
def test_https_through_upstream(juju: Juju):
    """Test HTTPS connectivity through the traefik -> istio chain with TLS on both."""
    data = get_relation_data(
        requirer_endpoint=f"{IPA_TESTER}/0:ingress",
        provider_endpoint=f"{APP_NAME}/0:ingress",
        model=juju.model,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    url = provider_app_data["url"]

    assert url.startswith("https://"), f"Expected HTTPS URL after TLS setup, got: {url}"

    ca_cert = get_ca_certificate(juju, f"{SELF_SIGNED_CERTS}/0")
    traefik_address = get_k8s_service_address(juju.model, TRAEFIK_APP)

    assert (
        send_http_request_with_custom_ca(url, ca_cert, resolve_netloc_to_ip=traefik_address) == 200
    ), f"Failed to reach tester through upstream chain with TLS: {url}"
