# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Ingress relation steps: deploy requirers, assert HTTPRoutes, verify routing."""

from jubilant import Juju
from pytest_bdd import given, then, when

from tests.integration import helpers
from tests.integration.helpers import APP_NAME

BOOKINFO = "bookinfo-productpage-k8s"
BOOKINFO_CHANNEL = "latest/stable"
CHARM_A = "charm-a"
CHARM_B = "charm-b"


def _deploy_requirer(juju: Juju, app: str) -> None:
    """Deploy a bookinfo requirer as ``app`` if not already present."""
    if app not in juju.status().apps:
        juju.deploy(BOOKINFO, app=app, channel=BOOKINFO_CHANNEL, trust=True)


def _ingress_related(juju: Juju, app: str) -> bool:
    """Return True if ``app`` is already related to the charm's ingress endpoint."""
    ingress_app = juju.status().apps.get(APP_NAME)
    rels = ingress_app.relations.get("ingress", []) if ingress_app else []
    return any(r.related_app == app for r in rels)


def _integrate(juju: Juju, app: str) -> None:
    """Relate ``app`` to the charm's ingress endpoint (idempotent)."""
    if not _ingress_related(juju, app):
        juju.integrate(f"{app}:ingress", f"{APP_NAME}:ingress")


@given("a charm that requires ingress is deployed")
def a_requirer_is_deployed(juju: Juju) -> None:
    """Deploy the primary ingress requirer (charm-a)."""
    _deploy_requirer(juju, CHARM_A)


@given("charm-a that requires ingress is deployed")
def charm_a_deployed(juju: Juju) -> None:
    """Deploy the charm-a ingress requirer."""
    _deploy_requirer(juju, CHARM_A)


@given("charm-b that requires ingress is deployed")
def charm_b_deployed(juju: Juju) -> None:
    """Deploy the charm-b ingress requirer."""
    _deploy_requirer(juju, CHARM_B)


@given("the ingress relation is established")
@when("the ingress relation is established")
def ingress_relation_established(juju: Juju) -> None:
    """Relate the primary requirer (charm-a) to the charm's ingress endpoint."""
    _integrate(juju, CHARM_A)


@when("the ingress relation is established with charm-a")
def ingress_relation_established_a(juju: Juju) -> None:
    """Relate charm-a to the charm's ingress endpoint."""
    _integrate(juju, CHARM_A)


@when("the ingress relation is established with charm-b")
def ingress_relation_established_b(juju: Juju) -> None:
    """Relate charm-b to the charm's ingress endpoint."""
    _integrate(juju, CHARM_B)


@when("the ingress relation is removed")
def ingress_relation_removed(juju: Juju) -> None:
    """Remove the primary requirer's ingress relation."""
    if _ingress_related(juju, CHARM_A):
        juju.remove_relation(f"{CHARM_A}:ingress", f"{APP_NAME}:ingress")


@then("no HTTPRoutes exist for ingress")
def no_httproutes_exist(juju: Juju) -> None:
    """Assert no requirer HTTPRoutes exist in the model."""
    assert helpers.list_httproutes(juju.model) == []


@then("an HTTPRoute exists for the requiring charm")
def httproute_exists_for_requirer(juju: Juju) -> None:
    """Assert an HTTPRoute was created for the primary requirer (charm-a)."""
    juju.wait(lambda _: helpers.httproute_exists(juju.model, CHARM_A), timeout=300, delay=5)


@then("the HTTPRoute references the Gateway")
def httproute_references_gateway(juju: Juju) -> None:
    """Assert the requirer's HTTPRoute has a parentRef to the charm's Gateway."""
    route = helpers.get_httproute(juju.model, CHARM_A)
    parent_refs = route.spec.get("parentRefs", [])
    assert any(ref.get("name") == APP_NAME for ref in parent_refs)


@then("the ingress URL is published in the relation data")
def ingress_url_published(juju: Juju) -> None:
    """Assert the charm published an ingress URL back to the requirer."""
    url = helpers.published_ingress_url(juju, CHARM_A)
    assert url and url.endswith(f"/{juju.model}-{CHARM_A}/")


@then("traffic to the ingress URL returns 200")
def traffic_returns_200(juju: Juju) -> None:
    """Assert requests to the published ingress URL route through to the backend."""
    url = helpers.published_ingress_url(juju, CHARM_A)
    juju.wait(lambda _: helpers.http_get_ok(url), timeout=300, delay=5)


@then("no HTTPRoutes exist for the previously related charm")
def no_httproute_for_previous(juju: Juju) -> None:
    """Assert the removed requirer's HTTPRoute was deleted."""
    juju.wait(lambda _: not helpers.httproute_exists(juju.model, CHARM_A), timeout=300, delay=5)


@then("an HTTPRoute exists for charm-a")
def httproute_exists_a(juju: Juju) -> None:
    """Assert charm-a has its own HTTPRoute."""
    juju.wait(lambda _: helpers.httproute_exists(juju.model, CHARM_A), timeout=300, delay=5)


@then("an HTTPRoute exists for charm-b")
def httproute_exists_b(juju: Juju) -> None:
    """Assert charm-b has its own HTTPRoute."""
    juju.wait(lambda _: helpers.httproute_exists(juju.model, CHARM_B), timeout=300, delay=5)
