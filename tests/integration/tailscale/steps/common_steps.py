"""Deployment, ingress, request, and scaling steps for Tailscale."""

import os
import subprocess
from urllib.parse import urljoin, urlsplit

import jubilant
from pytest_bdd import given, parsers, then, when

from integration.helpers import (
    curl_from_host,
    curl_from_juju_unit,
    verify_http_response,
    wait_for_active_idle_without_error,
)
from integration.tailscale.helpers import (
    deploy_bookinfo,
    deploy_charm,
    get_ingress_url,
    proxy_pods,
    request_productpage,
    wait_proxy_removed,
)
from integration.tailscale.steps.credential_steps import config_deployed


@given("a configured tailnet with an authenticated client")
def configured_tailnet(tailnet):
    """Require the prepared client without changing its enrollment."""
    assert tailnet


@given("a juju model with tailscale-k8s deployed")
def operator_deployed(tailscale_system_juju, terraform_state):
    """Deploy the cluster-wide operator using the solution Terraform root."""
    config = {
        "operator-tags": os.environ.get("TAILSCALE_OPERATOR_TAGS") or "tag:k8s-operator",
        "proxy-tags": os.environ.get("TAILSCALE_PROXY_TAGS") or "tag:k8s",
    }
    deploy_charm(tailscale_system_juju, "tailscale-k8s", terraform_state, config)


@given("a juju model with tailscale-config and tailscale-k8s deployed")
def system_deployed(tailscale_system_juju, terraform_state, credential_info):
    """Deploy the provider and operator without waiting for missing credentials."""
    operator_deployed(tailscale_system_juju, terraform_state)
    config_deployed(tailscale_system_juju, terraform_state, credential_info)


@given("a juju model for bookinfo services on the same cluster")
def bookinfo_model(juju):
    """Use pytest-jubilant's primary model, like the Istio suite."""
    assert juju.model is not None


@given("tailscale-beacon-k8s is deployed in the bookinfo model")
def beacon_deployed(juju, terraform_state):
    """Deploy the workload model's beacon with its default listen port."""
    deploy_charm(juju, "tailscale-beacon-k8s", terraform_state, {"listen-port": "80"})


@given("productpage has requested ingress from tailscale-beacon-k8s")
@when("you integrate productpage with tailscale-beacon-k8s over ingress")
def integrate_ingress(juju, ingress_relations, tailnet_devices, app="productpage"):
    """Request ingress through the charm relation and record its external resources."""
    juju.integrate(f"{app}:ingress", "tailscale-beacon-k8s:ingress")
    ingress_relations.append((juju, app))
    tailnet_devices.add(f"{juju.model.split(':')[-1]}-{app}")


@given(parsers.parse("the bookinfo services are deployed {ingress_enabled}"))
@when(parsers.parse("you deploy the bookinfo services {ingress_enabled}"))
def bookinfo_deployed(
    ingress_enabled, juju, terraform_state, bookinfo_config, ingress_relations, tailnet_devices
):
    """Deploy productpage and details, optionally relating productpage to the beacon."""
    assert ingress_enabled in (
        "with tailscale-beacon-k8s integration", "without tailscale-beacon-k8s integration"
    )
    deploy_bookinfo(juju, terraform_state, bookinfo_config)
    if ingress_enabled == "with tailscale-beacon-k8s integration":
        integrate_ingress(juju, ingress_relations, tailnet_devices)
        wait_for_active_idle_without_error([juju])


@given("the bookinfo services were exposed through tailscale-beacon-k8s")
def bookinfo_was_exposed(
    juju, terraform_state, bookinfo_config, ingress_relations, tailnet_devices, tailnet,
    juju_run_output,
):
    """Establish working ingress before the recreation scenario removes it."""
    bookinfo_deployed(
        "with tailscale-beacon-k8s integration", juju, terraform_state, bookinfo_config,
        ingress_relations, tailnet_devices,
    )
    productpage_reachable("productpage", juju, tailnet, juju_run_output)


@given("tailscale-beacon-k8s has listen-port set to 80")
def default_port(juju):
    """Establish the initial port explicitly."""
    juju.config("tailscale-beacon-k8s", {"listen-port": 80})


@when(parsers.parse("you set listen-port on tailscale-beacon-k8s to {port:d}"))
def change_port(port, juju, terraform_state):
    """Reapply the beacon's Terraform configuration, as Istio config steps do."""
    deploy_charm(juju, "tailscale-beacon-k8s", terraform_state, {"listen-port": str(port)})


@then("all charms are active")
def all_charms_active(juju, tailscale_system_juju, credential_info, ingress_relations):
    """Use the same shared readiness helper as Istio."""
    models = [juju, tailscale_system_juju, credential_info["provider"]]
    models.extend(workload for workload, _ in ingress_relations)
    wait_for_active_idle_without_error(list(dict.fromkeys(model for model in models if model)))


@when("tailnet client requests GET /productpage on the published ingress URL for productpage")
def request_ingress(juju, tailnet, juju_run_output):
    """Request the published URL directly from the enrolled runner."""
    juju.wait(lambda _: get_ingress_url(juju, "productpage") is not None, timeout=300)
    juju_run_output["last_request"] = request_productpage(juju, "productpage", tailnet)


@given(parsers.re(r"(?P<app>productpage(?:-b)?) is reachable through its published ingress URL"))
@then(parsers.re(r"(?P<app>productpage(?:-b)?) is reachable through its published ingress URL"))
def productpage_reachable(app, juju, tailnet, juju_run_output):
    """Wait for real tailnet traffic, checking HTTP status and recognizable page content."""
    def reachable(_):
        if not get_ingress_url(juju, app):
            return False
        try:
            result = request_productpage(juju, app, tailnet)
        except subprocess.TimeoutExpired:
            return False
        juju_run_output["last_request"] = result
        return (
            result["returncode"] == 0
            and "HTTP_CODE:200" in result["stdout"]
            and "The Comedy of Errors" in result["stdout"]
        )

    juju.wait(reachable, timeout=600, delay=5, error=jubilant.any_error)
    juju_run_output.setdefault("urls", {})[(juju.model, app)] = get_ingress_url(juju, app)


@when("productpage calls the details service")
def productpage_calls_details(juju, juju_run_output):
    """Use the shared unit request helper for cluster-local traffic."""
    juju_run_output["last_request"] = curl_from_juju_unit(
        juju, "productpage/0", "http://details:9080/details/0"
    )


@when("details requests GET /productpage on productpage:9080")
def details_calls_productpage(juju, juju_run_output):
    """Check that ingress does not replace cluster-local access."""
    juju_run_output["last_request"] = curl_from_juju_unit(
        juju, "details/0", "http://productpage:9080/productpage"
    )


@then("the request succeeds")
def request_succeeds(juju_run_output):
    """Use Istio's shared HTTP response assertion."""
    verify_http_response(juju_run_output["last_request"], expected_http_code=200, expected_exit_code=0)


@then("productpage returns the book information page")
def productpage_returns_book(juju_run_output):
    """Check the actual Bookinfo page rather than any successful HTTP response."""
    assert "The Comedy of Errors" in juju_run_output["last_request"]["stdout"]


@then("details returns valid book information")
def details_returns_book(juju_run_output):
    """Check the same Bookinfo response fields as the Istio suite."""
    assert any(
        field in juju_run_output["last_request"]["stdout"] for field in ("id", "type", "year", "ISBN")
    )


@then(parsers.parse("productpage has a published ingress URL with port {port:d} and path /"))
def published_port(port, juju):
    """Wait for the relation URL to reflect the configured ingress port."""
    def matches(_):
        url = get_ingress_url(juju, "productpage")
        if not url:
            return False
        parsed = urlsplit(url)
        return parsed.scheme == "http" and (parsed.port or 80) == port and parsed.path == "/"

    juju.wait(matches, timeout=300, error=jubilant.any_error)


@given("the ingress relation for productpage has been removed")
@when("you remove the ingress relation between productpage and tailscale-beacon-k8s")
@when("you remove the ingress relation for productpage in the first bookinfo model")
def remove_ingress(juju, tailscale_system_juju, ingress_relations, juju_run_output):
    """Remove ingress while the operator can still process the Service finalizer."""
    juju_run_output["previous_url"] = get_ingress_url(juju, "productpage")
    juju.remove_relation("productpage:ingress", "tailscale-beacon-k8s:ingress")
    wait_proxy_removed(tailscale_system_juju, juju, "productpage")
    ingress_relations.remove((juju, "productpage"))


@given("productpage has no published ingress URL")
@then("productpage has no published ingress URL")
@then("productpage in the first bookinfo model has no published ingress URL")
def no_ingress_url(juju):
    """Inspect the ingress relation, not productpage's local URL fallback."""
    juju.wait(lambda _: get_ingress_url(juju, "productpage") is None, timeout=300)


@then("the previous ingress URL for productpage is no longer reachable")
def previous_url_unreachable(juju, tailscale_system_juju, tailnet, juju_run_output):
    """Require deleted ingress resources and a healthy control path around failed requests."""
    url = juju_run_output["previous_url"]
    assert url and url == juju_run_output["urls"][(juju.model, "productpage")]
    assert get_ingress_url(juju, "productpage") is None
    wait_proxy_removed(tailscale_system_juju, juju, "productpage")
    control_url = juju_run_output["urls"][(juju.model, "productpage-b")]

    def control_is_reachable():
        assert get_ingress_url(juju, "productpage-b") == control_url
        result = request_productpage(juju, "productpage-b", tailnet)
        verify_http_response(result, expected_http_code=200, expected_exit_code=0)
        assert "The Comedy of Errors" in result["stdout"]

    def unreachable(_):
        control_is_reachable()
        try:
            result = curl_from_host(urljoin(url, "/productpage"), no_proxy=True)
        except subprocess.TimeoutExpired:
            unavailable = True
        else:
            # Only resolution, connection, and timeout failures indicate withdrawal.
            assert result["returncode"] in (0, 6, 7, 28), result["stderr"]
            unavailable = result["returncode"] != 0
        control_is_reachable()
        return unavailable

    juju.wait(unreachable, timeout=300, delay=5, error=jubilant.any_error)


@given("the tailnet proxy for productpage has been removed")
def proxy_removed(juju, tailscale_system_juju):
    """Require proxy deletion before revoking credentials."""
    wait_proxy_removed(tailscale_system_juju, juju, "productpage")


@when(parsers.parse("you restart {component}"))
def restart_component(component, juju, tailscale_system_juju):
    """Restart the operator service or delete its managed proxy pod."""
    if component == "the tailscale-k8s operator":
        tailscale_system_juju.ssh(
            "tailscale-k8s/0", "/charm/bin/pebble", "restart", "tailscale-operator",
            container="tailscale-operator",
        )
    else:
        assert component == "the tailnet proxy for productpage"
        pods = proxy_pods(tailscale_system_juju, juju, "productpage")
        assert pods, "No proxy pod to restart"
        subprocess.run(
            ["kubectl", "delete", "pod", "-n", tailscale_system_juju.model.split(":")[-1],
             *[pod["metadata"]["name"] for pod in pods], "--wait=true", "--timeout=120s"],
            check=True, capture_output=True, text=True, timeout=130,
        )


@then("the published ingress URL for productpage is unchanged")
def ingress_url_unchanged(juju, juju_run_output):
    """Compare against the URL captured before the scenario's action."""
    expected = juju_run_output["urls"][(juju.model, "productpage")]
    juju.wait(lambda _: get_ingress_url(juju, "productpage") == expected, timeout=300)


@given(parsers.parse("productpage has {units:d} units"))
@when(parsers.parse("you scale productpage to {units:d} units"))
def scale_productpage(units, juju, terraform_state, bookinfo_config):
    """Reapply Bookinfo with its complete application map and the requested scale."""
    bookinfo_config["productpage"]["units"] = units
    deploy_bookinfo(juju, terraform_state, bookinfo_config)
    juju.wait(lambda status: len(status.apps["productpage"].units) == units, timeout=600)
