"""Test helpers for the Tempo integration tests.

These are slightly modified from https://github.com/canonical/tempo-coordinator-k8s-operator/tree/main/tests/integration
"""

import copy
from dataclasses import asdict

from minio import Minio
from ops import Application
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import CharmDeploymentConfiguration

TEMPO_COORDINATOR_K8S = CharmDeploymentConfiguration(
    entity_url="tempo-coordinator-k8s",
    application_name="tempo-coordinator-k8s",
    channel="2/edge",
    trust=True,
)

TEMPO_WORKER_K8S = CharmDeploymentConfiguration(
    entity_url="tempo-worker-k8s",
    application_name="tempo-worker-k8s",
    channel="2/edge",
    trust=True,
)

S3_INTEGRATOR = CharmDeploymentConfiguration(
    entity_url="s3-integrator",
    application_name="s3-integrator",
    channel="2/edge",
    revision=157,
    trust=False,
)

MINIO = CharmDeploymentConfiguration(
    entity_url="minio",
    application_name="minio",
    channel="latest/edge",
    trust=True,
)

S3_CREDENTIALS_SECRET_LABEL = "s3-credentials"


async def deploy_monolithic_cluster(ops_test: OpsTest):
    """Deploy a monolithic tempo cluster."""
    coordinator_name = TEMPO_COORDINATOR_K8S.application_name
    worker_name = TEMPO_WORKER_K8S.application_name
    s3_integrator_name = S3_INTEGRATOR.application_name

    await ops_test.model.deploy(**asdict(TEMPO_COORDINATOR_K8S))
    await ops_test.model.deploy(**asdict(TEMPO_WORKER_K8S))
    await ops_test.model.deploy(**asdict(S3_INTEGRATOR))

    await ops_test.model.integrate(
        coordinator_name + ":s3", s3_integrator_name + ":s3-credentials"
    )
    await ops_test.model.integrate(
        coordinator_name + ":tempo-cluster", worker_name + ":tempo-cluster"
    )

    access_key = "minio123"
    secret_key = "minio123"
    bucket_name = "tempo"

    await deploy_and_configure_minio(
        s3_integrator=s3_integrator_name,
        access_key=access_key,
        secret_key=secret_key,
        bucket_name=bucket_name,
        ops_test=ops_test,
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[coordinator_name, worker_name, s3_integrator_name],
            status="active",
            timeout=2000,
            idle_period=30,
        )

    return coordinator_name


async def deploy_and_configure_minio(
    s3_integrator, access_key, secret_key, bucket_name, ops_test: OpsTest
):
    """Deploy and configure minio for tempo."""
    minio_name = MINIO.application_name
    config = {
        "access-key": access_key,
        "secret-key": secret_key,
    }
    minio_with_config = copy.deepcopy(MINIO)
    minio_with_config.config = config

    await ops_test.model.deploy(**asdict(minio_with_config))
    await ops_test.model.wait_for_idle(apps=[minio_name], status="active", timeout=2000)
    minio_addr = await get_unit_address(ops_test, minio_name, "0")

    mc_client = Minio(
        f"{minio_addr}:9000",
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )

    # create tempo bucket
    found = mc_client.bucket_exists(bucket_name)
    if not found:
        mc_client.make_bucket(bucket_name)

    # configure s3-integrator
    s3_integrator_app: Application = ops_test.model.applications[s3_integrator]
    s3_integrator_app_name = S3_INTEGRATOR.application_name

    credentials_secret_id = await ops_test.model.add_secret(
        name=S3_CREDENTIALS_SECRET_LABEL,
        data_args=[
            f"access-key={config.get('access-key')}",
            f"secret-key={config.get('secret-key')}",
        ],
    )
    await ops_test.model.grant_secret(
        secret_name=S3_CREDENTIALS_SECRET_LABEL,
        application=s3_integrator_app_name,
    )

    await s3_integrator_app.set_config(
        {
            "endpoint": f"minio-0.minio-endpoints.{ops_test.model.name}.svc.cluster.local:9000",
            "bucket": bucket_name,
            "credentials": credentials_secret_id,
        }
    )


async def get_unit_address(ops_test: OpsTest, app_name, unit_no):
    """Return the address of the unit with the given name and unit number."""
    status = await ops_test.model.get_status()
    app = status["applications"][app_name]
    if app is None:
        assert False, f"no app exists with name {app_name}"
    unit = app["units"].get(f"{app_name}/{unit_no}")
    if unit is None:
        assert False, f"no unit exists in app {app_name} with index {unit_no}"
    return unit["address"]
