# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Certificates relation steps for the envoy-ai-controller-k8s suite."""

from jubilant import Juju, all_active
from pytest_bdd import given, when

from tests.integration.helpers import APP_NAME

SSC = "self-signed-certificates"
SSC_CHANNEL = "latest/stable"


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
    """Relate the charm's certificates endpoint to SSC.

    Idempotent: scenarios share a model, so the relation may already exist from a
    prior scenario.
    """
    if not _certificates_related(juju):
        juju.integrate(f"{APP_NAME}:certificates", SSC)
