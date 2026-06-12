# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict, dataclass
from typing import Optional

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

# Model names
MODEL_ISTIO = "istio-system"
MODEL_IAM = "iam"
MODEL_INGRESS = "ingress"

# Relation endpoints
INGRESS_CONFIG_RELATION = "istio-ingress-config"
FORWARD_AUTH_RELATION = "forward-auth"
CERTIFICATES_RELATION = "certificates"
OAUTH_RELATION = "oauth"
DB_RELATION = "pg-database"
UNAUTH_INGRESS = "ingress-unauthenticated"
AUTH_INGRESS = "ingress"
RECEIVE_CA_CERT = "receive-ca-cert"
SEND_CA_CERT = "send-ca-cert"

oauth2_proxy_resources = {
    "oauth2-proxy-image": "ghcr.io/canonical/oauth2-proxy:7.8.1",
}


@dataclass
class CharmDeploymentConfiguration:
    entity_url: str
    application_name: str
    channel: str
    trust: bool
    config: Optional[dict] = None


# Charm configurations
ISTIO_K8S = CharmDeploymentConfiguration("istio-k8s", "istio-k8s", "latest/edge", True)

OAUTH2_PROXY = CharmDeploymentConfiguration(
    "oauth2-proxy-k8s", "oauth2-proxy", "latest/edge", True
)
INGRESS_ADMIN = CharmDeploymentConfiguration(
    "istio-ingress-k8s", "istio-ingress-admin", "latest/edge", True
)
INGRESS_PUBLIC = CharmDeploymentConfiguration(
    "istio-ingress-k8s", "istio-ingress-public", "latest/edge", True
)
CERTS = CharmDeploymentConfiguration(
    "self-signed-certificates",
    "self-signed-certificates",
    "latest/stable",
    False,
    config={"ca-common-name": "demo.ca.local"},
)
CATALOGUE_AUTHED = CharmDeploymentConfiguration(
    "catalogue-k8s", "catalogue-authed", "latest/edge", True
)
CATALOGUE_UNAUTHED = CharmDeploymentConfiguration(
    "catalogue-k8s", "catalogue-unauthed", "latest/edge", True
)

HYDRA = CharmDeploymentConfiguration("hydra", "hydra", "latest/edge", True)
KRATOS = CharmDeploymentConfiguration("kratos", "kratos", "latest/edge", True)
LOGIN_UI = CharmDeploymentConfiguration(
    "identity-platform-login-ui-operator",
    "identity-platform-login-ui-operator",
    "latest/edge",
    True,
)
POSTGRESQL = CharmDeploymentConfiguration(
    "postgresql-k8s",
    "postgresql-k8s",
    "14/stable",
    True,
    config={"plugin_pg_trgm_enable": True, "plugin_btree_gin_enable": True},
)


@pytest.mark.abort_on_fail
async def test_iam_bundle_split_deploy(ops_test: OpsTest):
    for model in [MODEL_ISTIO, MODEL_IAM, MODEL_INGRESS]:
        await ops_test.track_model(alias=model, model_name=model)

    istio_model = ops_test.models[MODEL_ISTIO]
    iam_model = ops_test.models[MODEL_IAM]
    ingress_model = ops_test.models[MODEL_INGRESS]

    await istio_model.model.deploy(**asdict(ISTIO_K8S))

    for charm in [HYDRA, KRATOS, LOGIN_UI, POSTGRESQL]:
        await iam_model.model.deploy(**asdict(charm))

    for charm in [INGRESS_ADMIN, INGRESS_PUBLIC, CERTS, CATALOGUE_AUTHED, CATALOGUE_UNAUTHED]:
        await ingress_model.model.deploy(**asdict(charm))

    await istio_model.model.wait_for_idle(timeout=1200)
    await iam_model.model.wait_for_idle(timeout=1200)
    await ingress_model.model.wait_for_idle(timeout=1200)


@pytest.mark.abort_on_fail
async def test_deploy_oauth_proxy(ops_test: OpsTest, oauth2_proxy_charm):
    ingress_model = ops_test.models[MODEL_INGRESS]
    await ingress_model.model.deploy(
        oauth2_proxy_charm,
        resources=oauth2_proxy_resources,
        application_name="oauth2-proxy",
        trust=True,
    )
    await ingress_model.model.wait_for_idle(["oauth2-proxy"], timeout=1000)


@pytest.mark.abort_on_fail
async def test_relations_setup(ops_test: OpsTest):
    iam_model = ops_test.models[MODEL_IAM]
    ingress_model = ops_test.models[MODEL_INGRESS]

    # Create offers
    offers = [
        (
            MODEL_ISTIO,
            ISTIO_K8S.application_name,
            INGRESS_CONFIG_RELATION,
            INGRESS_CONFIG_RELATION,
        ),
        (MODEL_IAM, HYDRA.application_name, OAUTH_RELATION, OAUTH_RELATION),
        (
            MODEL_INGRESS,
            INGRESS_PUBLIC.application_name,
            UNAUTH_INGRESS,
            "public-ingress-unauthenticated",
        ),
        (
            MODEL_INGRESS,
            INGRESS_PUBLIC.application_name,
            AUTH_INGRESS,
            "public-ingress-authenticated",
        ),
        (MODEL_INGRESS, INGRESS_ADMIN.application_name, AUTH_INGRESS, "admin-ingress"),
    ]
    for model, app, endpoint, offer_name in offers:
        full = f"{model}.{app}:{endpoint}"
        await ops_test.juju("offer", full, offer_name)

    # Consume offers
    consumes = [
        (MODEL_INGRESS, f"admin/{MODEL_ISTIO}.{INGRESS_CONFIG_RELATION}"),
        (MODEL_INGRESS, f"admin/{MODEL_IAM}.{OAUTH_RELATION}"),
        (MODEL_IAM, f"admin/{MODEL_INGRESS}.public-ingress-unauthenticated"),
        (MODEL_IAM, f"admin/{MODEL_INGRESS}.public-ingress-authenticated"),
        (MODEL_IAM, f"admin/{MODEL_INGRESS}.admin-ingress"),
    ]
    for model, offer in consumes:
        await ops_test.juju("consume", offer, "--model", model)

    # IAM model relations
    iam_relations = [
        (f"{HYDRA.application_name}:{DB_RELATION}", f"{POSTGRESQL.application_name}:database"),
        (f"{KRATOS.application_name}:{DB_RELATION}", f"{POSTGRESQL.application_name}:database"),
        (
            f"{KRATOS.application_name}:hydra-endpoint-info",
            f"{HYDRA.application_name}:hydra-endpoint-info",
        ),
        (
            f"{LOGIN_UI.application_name}:hydra-endpoint-info",
            f"{HYDRA.application_name}:hydra-endpoint-info",
        ),
        (
            f"{LOGIN_UI.application_name}:ui-endpoint-info",
            f"{HYDRA.application_name}:ui-endpoint-info",
        ),
        (
            f"{LOGIN_UI.application_name}:ui-endpoint-info",
            f"{KRATOS.application_name}:ui-endpoint-info",
        ),
        (f"{LOGIN_UI.application_name}:kratos-info", f"{KRATOS.application_name}:kratos-info"),
        (f"{HYDRA.application_name}:admin-ingress", "admin-ingress"),
        (f"{KRATOS.application_name}:admin-ingress", "admin-ingress"),
        (f"{KRATOS.application_name}:public-ingress", "public-ingress-unauthenticated"),
        (f"{HYDRA.application_name}:public-ingress", "public-ingress-unauthenticated"),
        (f"{LOGIN_UI.application_name}:ingress", "public-ingress-unauthenticated"),
    ]
    for a, b in iam_relations:
        await iam_model.model.add_relation(a, b)

    # Ingress model relations
    ingress_relations = [
        (
            f"{OAUTH2_PROXY.application_name}:ingress",
            f"{INGRESS_PUBLIC.application_name}:{UNAUTH_INGRESS}",
        ),
        (
            f"{CATALOGUE_UNAUTHED.application_name}:ingress",
            f"{INGRESS_PUBLIC.application_name}:{UNAUTH_INGRESS}",
        ),
        (
            f"{CATALOGUE_AUTHED.application_name}:ingress",
            f"{INGRESS_PUBLIC.application_name}:{AUTH_INGRESS}",
        ),
        (
            f"{INGRESS_ADMIN.application_name}:{CERTIFICATES_RELATION}",
            f"{CERTS.application_name}:{CERTIFICATES_RELATION}",
        ),
        (
            f"{INGRESS_PUBLIC.application_name}:{CERTIFICATES_RELATION}",
            f"{CERTS.application_name}:{CERTIFICATES_RELATION}",
        ),
        (
            f"{OAUTH2_PROXY.application_name}:{RECEIVE_CA_CERT}",
            f"{CERTS.application_name}:{SEND_CA_CERT}",
        ),
        (f"{OAUTH2_PROXY.application_name}:{OAUTH_RELATION}", OAUTH_RELATION),
        (f"{INGRESS_PUBLIC.application_name}:{INGRESS_CONFIG_RELATION}", INGRESS_CONFIG_RELATION),
        (
            f"{OAUTH2_PROXY.application_name}:{FORWARD_AUTH_RELATION}",
            f"{INGRESS_PUBLIC.application_name}:{FORWARD_AUTH_RELATION}",
        ),
    ]
    for a, b in ingress_relations:
        await ingress_model.model.add_relation(a, b)

    # Final wait for all models to be active/idle
    for model in ops_test.models.values():
        await model.model.wait_for_idle(status="active", timeout=1000, wait_for_active=True)
