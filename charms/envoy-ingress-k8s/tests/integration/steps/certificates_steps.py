# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""TLS certificates relation steps for the envoy-ingress-k8s suite."""

from jubilant import Juju, all_active
from pytest_bdd import given, then, when

from tests.integration import helpers
from tests.integration.helpers import APP_NAME, HTTP_LISTENER_NAME, HTTPS_LISTENER_NAME

SSC = "self-signed-certificates"
SSC_CHANNEL = "latest/stable"
TLS_SECRET_NAME = f"{APP_NAME}-tls"


def _certificates_related(juju: Juju) -> bool:
    """Return True if the charm's certificates endpoint is already related to SSC."""
    app = juju.status().apps.get(APP_NAME)
    rels = app.relations.get("certificates", []) if app else []
    return any(r.related_app == SSC for r in rels)


@given("the self-signed-certificates charm is deployed")
def ssc_deployed(juju: Juju) -> None:
    """Deploy self-signed-certificates if it is not already present."""
    if SSC in juju.status().apps:
        return
    juju.deploy(SSC, channel=SSC_CHANNEL)
    juju.wait(lambda s: all_active(s, SSC), timeout=1000, delay=5, successes=3)


@given("the certificates relation is established with self-signed-certificates")
@when("the certificates relation is established with self-signed-certificates")
def certificates_relation_established(juju: Juju) -> None:
    """Relate the charm's certificates endpoint to SSC (idempotent across scenarios)."""
    if not _certificates_related(juju):
        juju.integrate(f"{APP_NAME}:certificates", SSC)


@then("the Gateway has only HTTP listeners")
def gateway_http_only(juju: Juju) -> None:
    """Assert the Gateway exposes the HTTP listener and no HTTPS listener."""
    names = helpers.gateway_listener_names(juju.model)
    assert HTTP_LISTENER_NAME in names
    assert HTTPS_LISTENER_NAME not in names


@then("the Gateway has an HTTPS listener")
def gateway_has_https(juju: Juju) -> None:
    """Wait until the charm adds the HTTPS listener to the Gateway."""
    juju.wait(
        lambda _: HTTPS_LISTENER_NAME in helpers.gateway_listener_names(juju.model),
        timeout=300,
        delay=5,
    )


@then("the HTTPS listener references a TLS Secret")
def https_references_tls_secret(juju: Juju) -> None:
    """Assert the HTTPS listener's certificateRef points at an existing TLS Secret."""
    listener = helpers.gateway_listener(juju.model, HTTPS_LISTENER_NAME)
    refs = listener["tls"]["certificateRefs"]
    assert any(ref.get("name") == TLS_SECRET_NAME for ref in refs)
    assert helpers.tls_secret_exists(juju.model, TLS_SECRET_NAME)
