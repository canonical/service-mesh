# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import Optional

import pytest
import requests
import yaml
from conftest import (
    get_relation_data,
)
from helpers import (
    dequote,
    get_auth_policy_spec,
    get_ca_certificate,
    get_k8s_service_address,
    get_listener_condition,
    get_listener_spec,
    get_route_condition,
    send_http_request,
    send_http_request_with_custom_ca,
)
from jubilant import Juju, all_active

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
IPA_TESTER = "ipa-tester"
IPA_TESTER_UNAUTHENTICATED = "ipa-tester-unauthenticated"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy_dependencies")
def test_deploy_dependencies(juju: Juju, istio_core_juju: Juju, tester_http_charm):
    """Deploys dependencies for IPA tests."""
    # istio_core_juju fixture deploys istio-k8s in a separate model
    juju.deploy(
        tester_http_charm,
        app=IPA_TESTER,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.deploy(
        tester_http_charm,
        app=IPA_TESTER_UNAUTHENTICATED,
        resources={"echo-server-image": "jmalloc/echo-server:v0.3.7"},
    )
    juju.wait(
        lambda s: all_active(s, IPA_TESTER, IPA_TESTER_UNAUTHENTICATED),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_deployment", depends=["test_deploy_dependencies"])
def test_deployment(juju: Juju, istio_ingress_charm, resources):
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_relate", depends=["test_deployment"])
def test_relate(juju: Juju):
    juju.integrate(f"{IPA_TESTER}:ingress", "istio-ingress-k8s:ingress")
    juju.integrate(f"{IPA_TESTER_UNAUTHENTICATED}:ingress", "istio-ingress-k8s:ingress")
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER, IPA_TESTER_UNAUTHENTICATED),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(name="test_ipa_charm_has_ingress", depends=["test_relate"])
def test_ipa_charm_has_ingress(juju: Juju):
    """Spot check directly on the relation data that we have provided an ingress."""
    data = get_relation_data(
        requirer_endpoint="ipa-tester/0:ingress",
        provider_endpoint="istio-ingress-k8s/0:ingress",
        model=juju.model,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    url = provider_app_data["url"]
    requirer_app_data = data.requirer.application_data
    model = dequote(requirer_app_data["model"])
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")
    assert url == f"http://{istio_ingress_address}/{model}-ipa-tester"


@pytest.mark.dependency(name="test_auth_policy_validity", depends=["test_relate"])
def test_auth_policy_validity(juju: Juju):
    for ipa_tester in [IPA_TESTER, IPA_TESTER_UNAUTHENTICATED]:

        policy_name = f"{ipa_tester}-{APP_NAME}-{juju.model}-l4"

        # Retrieve the AuthorizationPolicy spec
        policy_spec = get_auth_policy_spec(juju.model, policy_name)

        # Ensure the policy spec is not None
        assert policy_spec is not None, f"AuthorizationPolicy '{policy_name}' not found."

        # Validate the 'rules' structure
        assert "rules" in policy_spec, "'rules' field is missing in the AuthorizationPolicy spec."
        rules = policy_spec["rules"]
        assert len(rules) == 1, "Expected exactly one rule in AuthorizationPolicy spec."

        # Validate the 'to' field inside the rule
        to_rules = rules[0].get("to", [])
        assert len(to_rules) == 1, "'to' field should contain exactly one operation."
        assert "operation" in to_rules[0], "Missing 'operation' in the 'to' field."
        assert to_rules[0]["operation"]["ports"] == ["8080"], (
            "Port mismatch in the AuthorizationPolicy."
        )

        # Validate the 'from' field inside the rule
        from_rules = rules[0].get("from", [])
        assert len(from_rules) == 1, "'from' field should contain exactly one source."
        assert "source" in from_rules[0], "Missing 'source' in the 'from' field."
        principals = from_rules[0]["source"].get("principals", [])
        assert len(principals) == 1, "Expected exactly one principal in the 'source' field."
        assert principals[0] == f"cluster.local/ns/{juju.model}/sa/istio-ingress-k8s-istio", (
            "Principal does not match expected format."
        )

        # Validate 'selector' field
        assert "selector" in policy_spec, (
            "'selector' field is missing in the AuthorizationPolicy spec."
        )
        match_labels = policy_spec["selector"].get("matchLabels", {})
        assert match_labels.get("app.kubernetes.io/name") == ipa_tester, (
            "AuthorizationPolicy selector does not match the expected app name."
        )


@pytest.mark.parametrize(
    "external_hostname, expected_hostname",
    [
        ("foo.bar", "foo.bar"),  # Initial valid hostname
        ("bar.foo", "bar.foo"),  # Change to a new valid hostname
        ("", None),  # Remove hostname
    ],
)
@pytest.mark.dependency(name="test_route_validity", depends=["test_relate"])
def test_route_validity(juju: Juju, external_hostname: str, expected_hostname: Optional[str]):
    """Test that routes to apps related on the ingress and ingress-unauthenticated endpoints work as expected."""
    juju.config(APP_NAME, {"external_hostname": external_hostname})
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER, IPA_TESTER_UNAUTHENTICATED),
        timeout=1000,
        delay=5,
        successes=3,
    )
    model = juju.model
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")
    listener_condition = get_listener_condition(juju.model, "istio-ingress-k8s")
    listener_spec = get_listener_spec(juju.model, "istio-ingress-k8s")
    assert listener_condition["attachedRoutes"] == 2
    assert listener_condition["conditions"][0]["message"] == "No errors found"
    assert listener_condition["conditions"][0]["reason"] == "Accepted"
    for ipa_tester in [IPA_TESTER, IPA_TESTER_UNAUTHENTICATED]:
        tester_url = f"http://{istio_ingress_address}/{model}-{ipa_tester}"
        # the route name will follow the format {ingressed_app_name}-{httproute or grpcroute}-{listener_name}-{ingress_app_name}
        route_condition = get_route_condition(
            juju.model, f"{ipa_tester}-httproute-http-80-{APP_NAME}"
        )
        assert route_condition["conditions"][0]["message"] == "Route was valid"
        assert route_condition["conditions"][0]["reason"] == "Accepted"
        assert route_condition["controllerName"] == "istio.io/gateway-controller"
        if not expected_hostname:
            assert "hostname" not in listener_spec
            assert send_http_request(tester_url)
        else:
            assert listener_spec["hostname"] == expected_hostname
            assert send_http_request(tester_url, {"Host": expected_hostname})
            assert not send_http_request(tester_url)
            assert not send_http_request(tester_url, {"Host": "random.hostname"})


@pytest.fixture(scope="module")
def deploy_and_relate_certificate_provider(juju: Juju):
    """Deploy the self-signed-certificates charm to the primary model and relate it to istio-ingress-k8s."""
    self_signed_certificates = "self-signed-certificates"
    juju.deploy(self_signed_certificates)
    juju.integrate(f"{self_signed_certificates}:certificates", f"{APP_NAME}:certificates")
    yield self_signed_certificates


@pytest.mark.parametrize(
    "external_hostname",
    [
        "",  # Use default (empty) hostname
        # Change to a new valid hostname.  This will reuse the existing relation to the cert provider, so it tests both
        # whether we can handle different hostnames and whether we can change the hostname while TLS is provided
        "foo.bar",
    ],
)
@pytest.mark.dependency(name="test_gateway_with_tls", depends=["test_relate"])
def test_gateway_with_tls(external_hostname, juju: Juju, deploy_and_relate_certificate_provider):
    """Test that, when connected to a TLS cert provider, the gateway is configured with TLS and http is redirected."""
    self_signed_certificates = deploy_and_relate_certificate_provider
    juju.config(APP_NAME, {"external_hostname": external_hostname})
    juju.wait(
        lambda s: all_active(s, APP_NAME, IPA_TESTER, self_signed_certificates),
        timeout=1000,
        delay=5,
        successes=3,
    )
    ca_certificate = get_ca_certificate(juju, f"{self_signed_certificates}/0")

    model = juju.model
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")
    tester_url = f"{istio_ingress_address}/{model}-{IPA_TESTER}"
    tester_url_http = f"http://{tester_url}"

    # If the ingress is configured to use a hostname, set the Host header
    hostname = juju.config(APP_NAME).get("external_hostname", None)
    headers = {}
    if hostname:
        headers["Host"] = hostname

    # Assert that http request is redirected to https
    resp = requests.get(url=tester_url_http, headers=headers, allow_redirects=False)
    assert resp.status_code == 301, "http request was not redirected to https"
    assert resp.headers.get("Location").startswith("https://"), (
        "http request was not redirected to https"
    )

    # Assert that https request works with the given ca-bundle
    if hostname:
        url = f"https://{hostname}/{model}-{IPA_TESTER}"
        resolve_netloc_to_ip = istio_ingress_address
    else:
        url = f"https://{istio_ingress_address}/{model}-{IPA_TESTER}"
        resolve_netloc_to_ip = None
    assert (
        send_http_request_with_custom_ca(
            url, ca_certificate, resolve_netloc_to_ip=resolve_netloc_to_ip
        )
        == 200
    ), "Failed to send request to endpoint with custom CA"


@pytest.mark.dependency(name="test_external_traffic_policy", depends=["test_relate"])
def test_external_traffic_policy(juju: Juju):
    """Test that the external-traffic-policy-cidrs config controls traffic access.

    The external traffic authorization policy creates an ALLOW rule for the Gateway.
    Traffic from IPs not in the configured CIDR blocks should be denied (403).
    """
    # Reset external_hostname to empty (previous test may have set it to "foo.bar")
    juju.config(APP_NAME, {"external_hostname": ""})
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=300, delay=5, successes=3)
    model = juju.model
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")
    tester_url = f"http://{istio_ingress_address}/{model}-{IPA_TESTER}"

    # Verify the external traffic auth policy exists with correct structure
    policy_name = f"{APP_NAME}-{model}-external-traffic"
    policy_spec = get_auth_policy_spec(model, policy_name)
    assert policy_spec is not None, f"AuthorizationPolicy '{policy_name}' not found."
    assert policy_spec["action"] == "ALLOW", (
        f"Expected ALLOW action, got {policy_spec.get('action')}"
    )
    assert "targetRefs" in policy_spec, "'targetRefs' field is missing"
    assert policy_spec["targetRefs"][0]["kind"] == "Gateway"

    # Test with default config (0.0.0.0/0) - traffic should be allowed
    # Note: verify=False is used because TLS may be enabled from previous test with self-signed certs
    response = requests.get(tester_url, verify=False)
    assert response.status_code == 200, (
        f"Expected 200 with default CIDR, got {response.status_code}"
    )

    # Change to a wrong IP - traffic should be denied
    juju.config(APP_NAME, {"external-traffic-policy-cidrs": "10.10.10.10"})
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=300, delay=5, successes=3)
    response = requests.get(tester_url, verify=False)
    assert response.status_code == 403, f"Expected 403 with wrong CIDR, got {response.status_code}"

    # Change back to permissive - traffic should be allowed again
    juju.config(APP_NAME, {"external-traffic-policy-cidrs": "0.0.0.0/0"})
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=300, delay=5, successes=3)
    response = requests.get(tester_url, verify=False)
    assert response.status_code == 200, (
        f"Expected 200 after restoring CIDR, got {response.status_code}"
    )


@pytest.mark.dependency(name="test_remove_relation", depends=["test_relate"])
def test_remove_relation(juju: Juju):
    juju.remove_relation(f"{IPA_TESTER}:ingress", "istio-ingress-k8s:ingress")
    juju.wait(lambda s: all_active(s, APP_NAME, IPA_TESTER), timeout=300, delay=5, successes=3)
