"""Integration tests for bookinfo details charm."""

import jubilant

APP_NAME = "bookinfo-details-k8s"


def test_details_deploy(juju, charm, resources):
    """Test basic deployment of details charm."""
    juju.deploy(charm, resources=resources)
    juju.wait(jubilant.all_active)

    status = juju.status()
    assert APP_NAME in status.apps
    assert status.apps[APP_NAME].is_active


def test_details_service_running(juju, charm, resources):
    """Test that the details service is properly running."""
    status = juju.status()
    unit_name = f"{APP_NAME}/0"

    assert status.apps[APP_NAME].units[unit_name].is_active


def test_details_health_endpoint(juju, charm, resources):
    """Test details service health endpoint returns 200."""
    # Use curl with -w flag to get HTTP status code
    result = juju.cli(
        "exec",
        "--unit",
        f"{APP_NAME}/0",
        "--",
        "curl",
        "-s",
        "-w",
        "%{http_code}",
        "-o",
        "/dev/null",
        "http://localhost:9080/health",
    )

    # Should return "200"
    assert result.strip() == "200"
