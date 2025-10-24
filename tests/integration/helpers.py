"""Helper functions for Service Mesh integration tests."""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import jubilant

logger = logging.getLogger(__name__)


class TFManager:
    """Simplified Terraform API."""

    _terraform = shutil.which("terraform") or shutil.which("tofu")

    def __init__(self, terraform_dir: Path, state_file: Optional[Path]):
        if not self._terraform:
            raise RuntimeError("Terraform or Opentofu binary not found in PATH.")
        self._terraform_dir = terraform_dir
        self._state_file = state_file

    def _run(
        self, cmd: List[str], env: Optional[Dict[str, str]] = None
    ) -> subprocess.CompletedProcess:
        """Run a terraform command."""
        cmd = [self._terraform, *cmd]  # type: ignore
        kwargs = {
            "cwd": self._terraform_dir,
            "capture_output": True,
            "text": True,
        }
        if env is not None:
            kwargs["env"] = env
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0:
            logger.error(
                f"Terraform {cmd[1]} failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
            raise RuntimeError(f"Terraform {cmd[1]} failed with code {result.returncode}")
        return result

    def init(self) -> None:
        """Initialize a terraform directory.

        Raises:
            RuntimeError: If terraform init fails
        """
        self._run(["init"])

    def apply(self, env: Dict[str, str]) -> None:
        """Apply terraform configuration.

        Args:
            env: Environment variables for the terraform command

        Raises:
            RuntimeError: If terraform apply fails
        """
        cmd = ["apply", "-auto-approve"]
        if self._state_file:
            cmd.append(f"-state={self._state_file}")
        self._run(cmd, env)

    def output(self, output_name: str) -> str:
        """Get output value from terraform state.

        Args:
            output_name: Name of the output variable

        Returns:
            The output value as a string

        Raises:
            RuntimeError: If terraform output fails
        """
        cmd = ["output"]
        if self._state_file:
            cmd.append(f"-state={self._state_file}")
        cmd.extend(["-raw", output_name])
        result = self._run(cmd)
        return result.stdout.strip()


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


# TODO: Implement a retry logic to prevent possible flaky tests.
def curl_from_juju_unit(
    juju: jubilant.Juju, unit: str, url: str, method: str = "GET", timeout: int = 30
) -> Dict[str, Any]:
    """Execute a curl command from a Juju unit to test connectivity.

    Args:
        juju: The Juju model instance
        unit: The unit to execute curl from (e.g., "productpage/0")
        url: The URL to curl (e.g., "http://details:9080/details/0")
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
        url,
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
