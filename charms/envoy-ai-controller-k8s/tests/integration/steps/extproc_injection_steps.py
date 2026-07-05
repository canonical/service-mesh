# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""ExtProc sidecar-injection steps for the envoy-ai-controller-k8s suite."""

from types import SimpleNamespace

from jubilant import Juju, all_agents_idle
from lightkube import Client
from pytest_bdd import given, then, when

from tests.integration.helpers import (
    ENVOY_CHANNEL,
    EXTPROC_CONTAINER,
    EXTPROC_REPO,
    INGRESS_APP,
    AIGatewayRoute,
    data_plane_pods,
)

ROUTE_NAME = "extproc-injection-itest"


@given("the envoy-ingress-k8s charm is deployed")
def ingress_deployed(juju: Juju) -> None:
    """Deploy the ingress charm — needed to provision a Gateway data-plane pod.

    Waits on agent idle rather than active. On substrates without a LoadBalancer
    implementation (CI), the Gateway address never resolves and the ingress unit
    parks in "Waiting for gateway address assignment" indefinitely. The Gateway
    CR is applied during config-changed regardless, so envoy-gateway still
    provisions the data-plane Deployment we need for the injection check.
    """
    if INGRESS_APP in juju.status().apps:
        return
    juju.deploy(INGRESS_APP, channel=ENVOY_CHANNEL, trust=True)
    juju.wait(lambda s: all_agents_idle(s, INGRESS_APP), timeout=1000, delay=5, successes=3)


@given("an AIGatewayRoute references the ingress Gateway")
def aigatewayroute_applied(juju: Juju, context: SimpleNamespace) -> None:
    """Apply a minimal AIGatewayRoute so the webhook injects extproc.

    Envoy AI Gateway's admission webhook only injects the extproc sidecar into
    data-plane pods whose parent Gateway is referenced by at least one
    AIGatewayRoute. A backend is deliberately omitted: the route's existence is
    enough to flip injection on, and no request-path traffic runs in this test.
    """
    client = Client()
    route = AIGatewayRoute(
        metadata={"name": ROUTE_NAME, "namespace": juju.model},
        spec={
            "parentRefs": [
                {
                    "group": "gateway.networking.k8s.io",
                    "kind": "Gateway",
                    "name": INGRESS_APP,
                }
            ],
            "rules": [
                {
                    "matches": [
                        {
                            "headers": [
                                {
                                    "type": "Exact",
                                    "name": "x-ai-eg-model",
                                    "value": "itest-noop",
                                }
                            ]
                        }
                    ],
                }
            ],
        },
    )
    client.apply(route, field_manager="pytest-extproc-injection")
    context.route_name = ROUTE_NAME


@when("the Envoy Gateway data-plane pod is recreated")
def dataplane_recreated(juju: Juju, context: SimpleNamespace) -> None:
    """Force the mutating webhook to re-fire and wait for an injected pod.

    The webhook only runs on pod CREATE, so pods that predate the AIGatewayRoute
    stay uninjected until they are replaced. Delete any existing data-plane pods
    (may be zero in fast substrates where the ReplicaSet has not spawned yet),
    then wait for a fresh pod that has both the extproc sidecar AND all
    containers Ready.
    """
    client = Client()
    for pod in data_plane_pods(juju.model):
        client.delete(type(pod), name=pod.metadata.name, namespace=juju.model)

    def injected(_status) -> bool:
        for pod in data_plane_pods(juju.model):
            if pod.metadata.deletionTimestamp is not None:
                continue
            if not any(c.name == EXTPROC_CONTAINER for c in pod.spec.containers):
                continue
            statuses = pod.status.containerStatuses or []
            if statuses and all(cs.ready for cs in statuses):
                context.pod = pod
                return True
        return False

    juju.wait(injected, timeout=300, delay=5, successes=2)


@then("the data-plane pod runs the ai-gateway-extproc container")
def dataplane_has_extproc(context: SimpleNamespace) -> None:
    """Assert the extproc sidecar is present in the recreated data-plane pod."""
    names = [c.name for c in context.pod.spec.containers]
    assert EXTPROC_CONTAINER in names, f"extproc missing from {names}"


@then(
    "the ai-gateway-extproc image matches the ai-gateway-image tag "
    "under the upstream extproc repo"
)
def extproc_image_matches_derivation(context: SimpleNamespace) -> None:
    """Assert the injected extproc URL points at the upstream Docker Hub repo.

    Regression guard for the ImagePullBackOff caused by stamping the Juju
    charm-store URL (registry.jujucharms.com/charm/<hash>/ai-extproc-image@...)
    onto data-plane pods that lacked the per-resource pull token. Anything
    starting with EXTPROC_REPO + ":" proves the derivation targeted upstream.
    """
    extproc = next(
        c for c in context.pod.spec.containers if c.name == EXTPROC_CONTAINER
    )
    assert extproc.image.startswith(f"{EXTPROC_REPO}:"), (
        f"extproc image {extproc.image!r} not derived from {EXTPROC_REPO}"
    )


@then("the data-plane pod is Ready")
def dataplane_ready(context: SimpleNamespace) -> None:
    """Assert every container in the injected data-plane pod is Ready."""
    statuses = context.pod.status.containerStatuses or []
    assert statuses and all(cs.ready for cs in statuses)
