"""Step definitions for authenticated ingress (IAM) tests."""

import logging
from typing import Dict

import jubilant
from pytest_bdd import given, then, when

from tests.integration.helpers import wait_for_active_idle_without_error
from tests.integration.istio.helpers import (
    deploy_bookinfo,
    deploy_iam,
    deploy_istio_ingress,
    deploy_oauth2_proxy,
)

logger = logging.getLogger(__name__)


# -------------- Given --------------


@given("istio-k8s offers istio-ingress-config")
def istio_offers_ingress_config(istio_system_juju: jubilant.Juju):
    """Create a cross-model offer for istio-ingress-config."""
    logger.info("Creating offer for istio:istio-ingress-config")
    istio_system_juju.offer(
        f"{istio_system_juju.model}.istio",
        endpoint="istio-ingress-config",
        name="ingress-config",
    )


@given("the Canonical Identity Platform is deployed")
def identity_platform_deployed(iam_info: Dict, iam_juju: jubilant.Juju):
    """Deploy the Canonical Identity Platform and store offer URLs."""
    if iam_info.get("deployed"):
        logger.info("Identity Platform already deployed, skipping")
        return

    logger.info("Deploying the Canonical Identity Platform")
    offers = deploy_iam(iam_juju)
    iam_info["oauth_offer_url"] = offers["oauth_offer_url"]
    iam_info["send_ca_cert_offer_url"] = offers["send_ca_cert_offer_url"]
    iam_info["certificates_offer_url"] = offers["certificates_offer_url"]
    iam_info["deployed"] = True


@given("bookinfo is deployed with authenticated ingress")
def bookinfo_with_authenticated_ingress(
    juju: jubilant.Juju,
    istio_system_juju: jubilant.Juju,
    iam_info: Dict,
    ingress_info: Dict,
    oauth2_info: Dict,
):
    """Ensure the full authenticated ingress stack is deployed and integrated."""
    if ingress_info.get("integrated"):
        logger.info("Authenticated ingress already set up, skipping")
        return

    # Deploy bookinfo
    deploy_bookinfo(juju)

    # Deploy istio-ingress and oauth2-proxy
    ingress_app = deploy_istio_ingress(juju)
    ingress_info["app_name"] = ingress_app

    oauth2_app = deploy_oauth2_proxy(juju, config={"dev": "true"})
    oauth2_info["app_name"] = oauth2_app

    # Consume cross-model offers from IAM
    juju.consume(iam_info["oauth_offer_url"])
    juju.consume(iam_info["send_ca_cert_offer_url"])
    juju.consume(iam_info["certificates_offer_url"])

    # Consume istio ingress config offer
    juju.consume(f"{istio_system_juju.model}.ingress-config")

    # Integrate charms
    juju.integrate("productpage:ingress", f"{ingress_app}:ingress")
    juju.integrate(oauth2_app, "oauth-offer")
    juju.integrate(f"{oauth2_app}:forward-auth", f"{ingress_app}:forward-auth")
    juju.integrate(f"{oauth2_app}:receive-ca-cert", "send-ca-cert")
    juju.integrate(ingress_app, "ingress-config")
    juju.integrate(f"{ingress_app}:certificates", "certificates")
    juju.integrate(f"{oauth2_app}:ingress", f"{ingress_app}:ingress-unauthenticated")

    wait_for_active_idle_without_error([juju], timeout=60 * 20)
    ingress_info["integrated"] = True


# -------------- When --------------


@when("you deploy bookinfo")
def deploy_bookinfo_step(juju: jubilant.Juju):
    """Deploy the bookinfo charms."""
    logger.info(f"Deploying bookinfo to {juju.model}")
    deploy_bookinfo(juju)


@when("you add an istio-ingress with oauth2-proxy")
def add_istio_ingress_with_oauth2(juju: jubilant.Juju, ingress_info: Dict, oauth2_info: Dict):
    """Deploy istio-ingress-k8s and oauth2-proxy-k8s."""
    logger.info(f"Adding istio-ingress and oauth2-proxy to {juju.model}")

    ingress_app = deploy_istio_ingress(juju)
    ingress_info["app_name"] = ingress_app

    oauth2_app = deploy_oauth2_proxy(juju, config={"dev": "true"})
    oauth2_info["app_name"] = oauth2_app


@when("you integrate this model with iam")
def integrate_model_with_iam(juju: jubilant.Juju, iam_info: Dict, oauth2_info: Dict):
    """Consume IAM offers and integrate oauth2-proxy with the identity platform."""
    logger.info("Integrating model with IAM")

    juju.consume(iam_info["oauth_offer_url"])
    juju.consume(iam_info["send_ca_cert_offer_url"])
    juju.consume(iam_info["certificates_offer_url"])

    oauth2_app = oauth2_info["app_name"]
    juju.integrate(oauth2_app, "oauth-offer")
    juju.integrate(f"{oauth2_app}:receive-ca-cert", "send-ca-cert")


@when("you integrate the ingress with istio")
def integrate_ingress_with_istio(
    juju: jubilant.Juju,
    istio_system_juju: jubilant.Juju,
    ingress_info: Dict,
    oauth2_info: Dict,
):
    """Consume istio offer and set up ingress integrations."""
    logger.info("Integrating ingress with istio")

    ingress_app = ingress_info["app_name"]
    oauth2_app = oauth2_info["app_name"]

    juju.consume(f"{istio_system_juju.model}.ingress-config")

    juju.integrate("productpage:ingress", f"{ingress_app}:ingress")
    juju.integrate(f"{oauth2_app}:forward-auth", f"{ingress_app}:forward-auth")
    juju.integrate(ingress_app, "ingress-config")
    juju.integrate(f"{ingress_app}:certificates", "certificates")
    juju.integrate(f"{oauth2_app}:ingress", f"{ingress_app}:ingress-unauthenticated")

    wait_for_active_idle_without_error([juju], timeout=60 * 20)
    ingress_info["integrated"] = True


# -------------- Then --------------


@then("the request is redirected to the login page")
def request_is_redirected(juju_run_output: dict):
    """Verify the request was intercepted by oauth2-proxy.

    oauth2-proxy redirects unauthenticated requests to the identity provider
    with an HTTP 302.
    """
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    stdout = result["stdout"]
    assert "HTTP_CODE:302" in stdout, f"Expected HTTP redirect (302), got: {stdout[-200:]}"
