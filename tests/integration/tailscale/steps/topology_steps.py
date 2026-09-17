"""Step definitions for multi-application and cross-model Tailscale ingress."""

from urllib.parse import urlsplit

from pytest_bdd import given, then, when

from integration.helpers import verify_http_response, wait_for_active_idle_without_error
from integration.tailscale.helpers import (
    deploy_bookinfo,
    deploy_charm,
    get_ingress_url,
    request_productpage,
)
from integration.tailscale.steps.common_steps import integrate_ingress, productpage_reachable
from integration.tailscale.steps.credential_steps import integrate_credentials


@given("productpage and productpage-b are exposed through the same tailscale-beacon-k8s")
def multiple_applications(
    juju, terraform_state, bookinfo_config, ingress_relations, tailnet_devices, tailnet,
    juju_run_output,
):
    """Expose two real productpage applications through one beacon."""
    bookinfo_config["productpage-b"] = {}
    deploy_bookinfo(juju, terraform_state, bookinfo_config)
    for app in bookinfo_config:
        integrate_ingress(juju, ingress_relations, tailnet_devices, app)
        productpage_reachable(app, juju, tailnet, juju_run_output)


@given("productpage is exposed through tailscale-beacon-k8s in each of two bookinfo models on the same cluster")
def multiple_models(
    juju, second_bookinfo_juju, terraform_state, ingress_relations, tailnet_devices,
    tailnet, juju_run_output,
):
    """Use the plugin's second model; keep the single operator cluster-wide."""
    deploy_charm(second_bookinfo_juju, "tailscale-beacon-k8s", terraform_state)
    for workload in (juju, second_bookinfo_juju):
        deploy_bookinfo(workload, terraform_state, {"productpage": {}})
        integrate_ingress(workload, ingress_relations, tailnet_devices)
        productpage_reachable("productpage", workload, tailnet, juju_run_output)


@when("tailnet client requests GET /productpage on each application's published ingress URL")
@when("tailnet client requests GET /productpage on each model's published ingress URL for productpage")
def request_each_ingress(ingress_relations, tailnet, juju_run_output):
    """Make independent runner requests to each relation's published URL."""
    juju_run_output["requests"] = [
        request_productpage(workload, app, tailnet) for workload, app in ingress_relations
    ]


@then("each request succeeds")
def each_request_succeeds(juju_run_output):
    """Check that both endpoints serve Bookinfo, not merely successful responses."""
    results = juju_run_output["requests"]
    assert len(results) == 2
    for result in results:
        verify_http_response(result, expected_http_code=200, expected_exit_code=0)
        assert "The Comedy of Errors" in result["stdout"]


@then("the applications have distinct published ingress URLs")
def distinct_application_urls(juju):
    """Check each application's separate relation URL."""
    urls = [get_ingress_url(juju, app) for app in ("productpage", "productpage-b")]
    assert all(urls) and len(set(urls)) == 2


@then("productpage in each model has a distinct model-qualified ingress hostname")
def distinct_model_hostnames(juju, second_bookinfo_juju, tailnet):
    """Check the beacon's model-qualified names on the actual client tailnet."""
    hostnames = []
    for workload in (juju, second_bookinfo_juju):
        url = get_ingress_url(workload, "productpage")
        assert url
        hostname = urlsplit(url).hostname
        assert hostname == f"{workload.model.split(':')[-1]}-productpage.{tailnet}"
        hostnames.append(hostname)
    assert len(set(hostnames)) == 2


@then("productpage in the second bookinfo model is reachable through its published ingress URL")
def second_model_reachable(second_bookinfo_juju, tailnet, juju_run_output):
    """Request the surviving model's ingress after the first model loses ingress."""
    productpage_reachable("productpage", second_bookinfo_juju, tailnet, juju_run_output)


@given("tailscale-config is deployed in a separate juju model")
def separate_provider(credentials_juju, terraform_state, credential_info):
    """Deploy the same provider charm in a separate factory-managed model."""
    deploy_charm(credentials_juju, "tailscale-config", terraform_state)
    credential_info["provider"] = credentials_juju
    credential_info["remote"] = "remote-credentials"


@when("you integrate tailscale-config with tailscale-k8s over tailscale-credentials across models")
def integrate_across_models(tailscale_system_juju, credential_info):
    """Use Jubilant's native offer, consume, and integrate methods, like Istio IAM."""
    provider = credential_info["provider"]
    model = provider.status().model
    provider.offer(
        f"{model.name}.tailscale-config", endpoint="tailscale-credentials", controller=model.controller
    )
    tailscale_system_juju.consume(
        f"{model.name}.tailscale-config", alias=credential_info["remote"], controller=model.controller
    )
    integrate_credentials(tailscale_system_juju, credential_info)
    wait_for_active_idle_without_error([provider, tailscale_system_juju])
