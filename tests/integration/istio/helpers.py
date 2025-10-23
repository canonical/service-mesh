"""Helper functions for Service Mesh integration tests."""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import jubilant
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource

logger = logging.getLogger(__name__)

# Define AuthorizationPolicy as a lightkube generic resource
AuthorizationPolicy = create_namespaced_resource(
    group="security.istio.io",
    version="v1beta1",
    kind="AuthorizationPolicy",
    plural="authorizationpolicies",
)

# Find terraform binary
TERRAFORM = shutil.which("terraform") or shutil.which("tofu")
if not TERRAFORM:
    raise RuntimeError("terraform or tofu binary not found in PATH")

# Istio configuration
ISTIO_CHANNEL = os.environ.get("ISTIO_CHANNEL", "2/edge")


def wait_for_active_idle_without_error(jujus: List[jubilant.Juju], timeout: int = 60 * 20):
    """Wait for all Juju models to be active and idle without errors.

    Args:
        jujus: List of Juju model instances to wait for
        timeout: Maximum time to wait for models to settle (default: 20 minutes)
    """
    for juju in jujus:
        # Wait for all applications to be active
        juju.wait(jubilant.all_active, delay=5, successes=5, timeout=timeout)

        # Wait for active state with error checking
        juju.wait(jubilant.all_active, delay=5, timeout=60 * 5, error=jubilant.any_error)

        # Wait for all agents to be idle with error checking
        juju.wait(
            jubilant.all_agents_idle,
            delay=5,
            timeout=60 * 5,
            error=jubilant.any_error,
        )


def get_authorization_policies(juju: jubilant.Juju) -> List[str]:
    """Get list of AuthorizationPolicy resources in the model's namespace.

    Args:
        juju: The Juju model instance

    Returns:
        List of AuthorizationPolicy names
    """
    assert juju.model is not None, "Juju model is not set"

    try:
        client = Client()
        policies = client.list(AuthorizationPolicy, namespace=juju.model)
        policy_names = [
            policy.metadata.name
            for policy in policies
            if policy.metadata is not None and policy.metadata.name is not None
        ]
        logger.info(
            f"Found {len(policy_names)} authorization policies in {juju.model}: {policy_names}"
        )
        return policy_names
    except Exception as e:
        logger.error(f"Failed to get authorization policies: {e}")
        return []


def curl_service(
    juju: jubilant.Juju, unit: str, service_url: str, method: str = "GET", timeout: int = 30
) -> Dict[str, Any]:
    """Execute a curl command from a Juju unit to test service connectivity.

    Args:
        juju: The Juju model instance
        unit: The unit to execute curl from (e.g., "productpage/0")
        service_url: The URL to curl (e.g., "http://details:9080/details/0")
        method: HTTP method to use (default: "GET")
        timeout: Command timeout in seconds (default: 30)

    Returns:
        Dictionary with stdout, stderr, and returncode
    """
    cmd = [
        "juju",
        "exec",
        "--model",
        juju.model,
        "--unit",
        unit,
        "--",
        "curl",
        "-X",
        method,
        "-s",
        "-w",
        "\\nHTTP_CODE:%{http_code}",
        service_url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


def verify_http_response(
    curl_result: Dict[str, Any],
    expected_http_code: Optional[int] = None,
    expected_exit_code: Optional[int] = None,
) -> None:
    """Verify that a curl result matches expected HTTP code and/or exit code.

    Args:
        curl_result: Dictionary returned from curl_service()
        expected_http_code: Expected HTTP status code (e.g., 200, 403). If None, HTTP code is not checked.
        expected_exit_code: Expected command exit code (e.g., 0 for success, 1 for failure). If None, exit code is not checked.

    Raises:
        AssertionError: If the result does not match expectations

    Examples:
        # Verify successful HTTP 200 response
        verify_http_response(result, expected_http_code=200, expected_exit_code=0)

        # Verify service mesh blocks request with 403
        verify_http_response(result, expected_http_code=403, expected_exit_code=0)

        # Verify curl command failed (e.g., connection refused)
        verify_http_response(result, expected_exit_code=1)
    """
    if expected_exit_code is not None:
        assert curl_result["returncode"] == expected_exit_code, (
            f"Expected exit code {expected_exit_code}, got {curl_result['returncode']}\nSTDERR: {curl_result['stderr']}"
        )

    if expected_http_code is not None:
        stdout = curl_result["stdout"]
        http_code_string = f"HTTP_CODE:{expected_http_code}"
        assert http_code_string in stdout, f"Expected HTTP {expected_http_code}, got: {stdout}"


def terraform_init(terraform_dir: Path) -> None:
    """Initialize a terraform directory.

    Args:
        terraform_dir: Path to the terraform directory

    Raises:
        RuntimeError: If terraform init fails
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    result = subprocess.run(
        [TERRAFORM, "init"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Terraform init failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        raise RuntimeError(f"Terraform init failed with code {result.returncode}")


def terraform_apply(terraform_dir: Path, state_file: Path, env: Dict[str, str]) -> None:
    """Apply terraform configuration.

    Args:
        terraform_dir: Path to the terraform directory
        state_file: Path to the terraform state file
        env: Environment variables for the terraform command

    Raises:
        RuntimeError: If terraform apply fails
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    result = subprocess.run(
        [TERRAFORM, "apply", "-auto-approve", f"-state={state_file}"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        logger.error(f"Terraform apply failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        raise RuntimeError(f"Terraform apply failed with code {result.returncode}")


def terraform_output(terraform_dir: Path, state_file: Path, output_name: str) -> str:
    """Get output value from terraform state.

    Args:
        terraform_dir: Path to the terraform directory
        state_file: Path to the terraform state file
        output_name: Name of the output variable

    Returns:
        The output value as a string

    Raises:
        RuntimeError: If terraform output fails
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    result = subprocess.run(
        [TERRAFORM, "output", f"-state={state_file}", "-raw", output_name],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Terraform output failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        raise RuntimeError(f"Terraform output failed with code {result.returncode}")

    return result.stdout.strip()


def scale_application(
    juju: jubilant.Juju,
    app_name: str,
    units: int,
    beacon_app_name: Optional[str] = None,
    beacon_service_mesh_endpoint: Optional[str] = None,
) -> None:
    """Scale a bookinfo application using terraform.

    Args:
        juju: The Juju model instance
        app_name: The name of the application to scale (e.g., "productpage", "details")
        units: The desired number of units
        beacon_app_name: Optional name of the istio-beacon application
        beacon_service_mesh_endpoint: Optional endpoint name for beacon's service mesh integration
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent.parent.parent.parent / "terraform" / "bookinfo"
    state_file = Path(tempfile.gettempdir()) / f"bookinfo-{juju.model}.tfstate"

    logger.info(f"Scaling {app_name} to {units} units")

    # Build terraform variables
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": "latest/stable",
            f"TF_VAR_{app_name}": json.dumps({"units": units}),
        }
    )

    if beacon_app_name:
        env["TF_VAR_beacon_app_name"] = beacon_app_name
    if beacon_service_mesh_endpoint:
        env["TF_VAR_beacon_service_mesh_endpoint"] = beacon_service_mesh_endpoint

    terraform_apply(terraform_dir, state_file, env)


def deploy_istio(juju: jubilant.Juju) -> None:
    """Deploy istio-k8s to a Juju model using terraform.

    Args:
        juju: The Juju model instance to deploy to
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent.parent.parent.parent / "terraform" / "istio"
    state_file = Path(tempfile.gettempdir()) / f"istio-{juju.model}.tfstate"

    logger.info(f"Deploying istio-k8s to {juju.model} (channel={ISTIO_CHANNEL})")

    terraform_init(terraform_dir)

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": ISTIO_CHANNEL,
        }
    )

    terraform_apply(terraform_dir, state_file, env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)


def deploy_istio_beacon(juju: jubilant.Juju, managed_mode: bool = True) -> tuple[str, str]:
    """Deploy istio-beacon to a Juju model using terraform and return app name and endpoint.

    Args:
        juju: The Juju model instance to deploy to
        managed_mode: Whether beacon should manage authorization policies (default: True)

    Returns:
        Tuple of (app_name, service_mesh_endpoint)
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent.parent.parent.parent / "terraform" / "istio-beacon"
    state_file = Path(tempfile.gettempdir()) / f"istio-beacon-{juju.model}.tfstate"

    logger.info(
        f"Deploying istio-beacon to {juju.model} (channel={ISTIO_CHANNEL}, managed_mode={managed_mode})"
    )

    terraform_init(terraform_dir)

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": ISTIO_CHANNEL,
            "TF_VAR_config": json.dumps(
                {
                    "manage-authorization-policies": str(managed_mode).lower(),
                }
            ),
        }
    )

    terraform_apply(terraform_dir, state_file, env)

    # Get the beacon app name and service mesh endpoint from terraform output
    app_name = terraform_output(terraform_dir, state_file, "app_name")
    service_mesh_endpoint = terraform_output(terraform_dir, state_file, "service_mesh_endpoint")

    logger.info(f"Istio-beacon deployed: app={app_name}, endpoint={service_mesh_endpoint}")

    wait_for_active_idle_without_error([juju], timeout=60 * 20)

    return app_name, service_mesh_endpoint


def deploy_bookinfo(
    juju: jubilant.Juju,
    beacon_app_name: Optional[str] = None,
    beacon_service_mesh_endpoint: Optional[str] = None,
) -> None:
    """Deploy the bookinfo stack to a Juju model using terraform.

    Args:
        juju: The Juju model instance to deploy to
        beacon_app_name: Optional name of the istio-beacon application. If provided, enables service mesh integration.
        beacon_service_mesh_endpoint: Optional endpoint name for beacon's service mesh integration.
    """
    assert TERRAFORM is not None, "Terraform binary not found"
    assert juju.model is not None, "Juju model is not set"

    terraform_dir = Path(__file__).parent.parent.parent.parent / "terraform" / "bookinfo"
    state_file = Path(tempfile.gettempdir()) / f"bookinfo-{juju.model}.tfstate"

    logger.info(
        f"Deploying bookinfo to {juju.model} (beacon={beacon_app_name}, endpoint={beacon_service_mesh_endpoint})"
    )

    terraform_init(terraform_dir)

    # Apply terraform configuration
    env = os.environ.copy()
    env.update(
        {
            "TF_VAR_model": juju.model,
            "TF_VAR_channel": "latest/stable",
        }
    )

    if beacon_app_name:
        env["TF_VAR_beacon_app_name"] = beacon_app_name
    if beacon_service_mesh_endpoint:
        env["TF_VAR_beacon_service_mesh_endpoint"] = beacon_service_mesh_endpoint

    terraform_apply(terraform_dir, state_file, env)
    wait_for_active_idle_without_error([juju], timeout=60 * 20)
