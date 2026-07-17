#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict

import pytest
from helpers import (
    ISTIO_K8S,
    KIALI_NAME,
)
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import CharmDeploymentConfiguration
from tests.integration.tempo_helpers import TEMPO_COORDINATOR_K8S, deploy_monolithic_cluster
from tests.integration.test_charm import (
    test_add_relations_to_required_dependencies as add_relations_to_required_dependencies,
)
from tests.integration.test_charm import test_build_and_deploy as build_and_deploy
from tests.integration.test_charm import (
    test_deploy_required_dependencies as deploy_required_dependencies,
)
from tests.integration.test_charm import test_kiali_is_available as kiali_is_available

logger = logging.getLogger(__name__)
TEMPO_NAME = TEMPO_COORDINATOR_K8S.application_name

GRAFANA_K8S = CharmDeploymentConfiguration(
    entity_url="grafana-k8s",
    application_name="grafana-k8s",
    channel="2/edge",
    trust=True,
    config={
        "allow_anonymous_access": "true",
    },
)
GRAFANA_NAME = GRAFANA_K8S.application_name


@pytest.mark.setup
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm_under_test and deploy it."""
    await build_and_deploy(ops_test, charm_under_test)


@pytest.mark.setup
@pytest.mark.dependency
@pytest.mark.abort_on_fail
async def test_deploy_required_dependencies(ops_test: OpsTest):
    """Deploy the integration test dependencies."""
    await deploy_required_dependencies(ops_test)


@pytest.mark.setup
@pytest.mark.dependency
@pytest.mark.abort_on_fail
async def test_add_relations_to_required_dependencies(ops_test: OpsTest):
    """Relate the charm_under_test to prometheus and istio-k8s."""
    await add_relations_to_required_dependencies(ops_test)


@pytest.mark.setup
@pytest.mark.dependency
@pytest.mark.abort_on_fail
async def test_deploy_grafana(ops_test: OpsTest):
    """Deploy grafana for integration with Kiali and Tempo."""
    await ops_test.model.deploy(**asdict(GRAFANA_K8S))
    await ops_test.model.wait_for_idle(
        apps=[GRAFANA_K8S.application_name], status="active", timeout=1000
    )


@pytest.mark.setup
@pytest.mark.dependency
@pytest.mark.abort_on_fail
async def test_deploy_tempo(ops_test: OpsTest):
    """Deploy and configure a monolithic Tempo instance to integrate it to our existing dependencies for testing."""
    await deploy_monolithic_cluster(ops_test)
    await ops_test.model.add_relation(f"{TEMPO_NAME}:grafana-source", GRAFANA_NAME)

    await ops_test.model.wait_for_idle(
        apps=[TEMPO_NAME, GRAFANA_NAME, ISTIO_K8S.application_name], status="active", timeout=1000
    )


@pytest.mark.setup
@pytest.mark.dependency
@pytest.mark.abort_on_fail
async def test_relate_istio_to_tempo(ops_test: OpsTest):
    """Relate istio-k8s to tempo to configure workload tracing forwarding."""
    await ops_test.model.add_relation(
        f"{ISTIO_K8S.application_name}:workload-tracing", f"{TEMPO_NAME}:tracing"
    )

    await ops_test.model.wait_for_idle(
        apps=[ISTIO_K8S.application_name, TEMPO_NAME], status="active", timeout=1000
    )


@pytest.mark.setup
@pytest.mark.dependency
@pytest.mark.abort_on_fail
async def test_add_relation_from_kiali_to_tempo_and_grafana(ops_test: OpsTest):
    """Relate Kiali to tempo."""
    await ops_test.model.add_relation(f"{KIALI_NAME}:tempo-api", f"{TEMPO_NAME}")
    await ops_test.model.add_relation(
        f"{KIALI_NAME}:tempo-datasource-exchange", f"{TEMPO_NAME}:receive-datasource"
    )
    await ops_test.model.add_relation(f"{KIALI_NAME}:grafana-metadata", f"{GRAFANA_NAME}")

    await ops_test.model.wait_for_idle(
        apps=[KIALI_NAME, TEMPO_NAME, GRAFANA_NAME], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_kiali_is_available(ops_test: OpsTest):
    """Assert that Kiali is up and available inside the cluster."""
    await kiali_is_available(ops_test)


# TODO: This confirms the charms assemble together, not that tracing is actually visible in Kiali.  Should we automate
#  that?
#
#  To manually confirm this, execute the above tests, keep the model, deploy a workload, and inspect in Kiali:
#   juju add-model kiali
#   tox -e integration -- --model kiali tests/integration/test_tempo_integration.py
#   juju add-model bookinfo
#   juju deploy istio-beacon-k8s --trust --channel edge --config model-on-mesh=true
#   kubectl -n bookinfo apply -f https://raw.githubusercontent.com/istio/istio/refs/heads/master/samples/bookinfo/platform/kube/bookinfo.yaml
#   # Generate traffic:
#   while true; do kubectl -n bookinfo exec "$(kubectl -n bookinfo get pod -l app=ratings -o jsonpath='{.items[0].metadata.name}')" -c ratings -- curl -sS grafana-on-mesh:3000  | grep -o "<title>.*</title>"; sleep 1; done
#   # Check in the Kiali dashboard for traces to the bookinfo app
#  Note that until https://github.com/canonical/istio-k8s-operator/issues/30 is resolved, we also need to do the
#  following so istio can forward traces to tempo:
#   cat << EOF | kubectl apply -n kiali -f -
#   apiVersion: networking.istio.io/v1alpha3
#   kind: ServiceEntry
#   metadata:
#     name: tempo
#   spec:
#     hosts:
#     - tempo-coordinator-k8s-0.tempo-coordinator-k8s-endpoints.kiali.svc.cluster.local
#     ports:
#     - number: 4317
#       name: grpc-otel
#       protocol: GRPC
#     resolution: DNS
#   EOF
