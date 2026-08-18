"""Integration tests for bookinfo productpage charm."""

import jubilant

APP_NAME = "bookinfo-productpage-k8s"


def test_productpage_deploy_waiting(juju, charm, resources):
    """Test productpage deployment initially waits for backend services."""
    juju.deploy(charm, resources=resources, app=APP_NAME)

    # Wait for the charm to be deployed but not necessarily active
    juju.wait(lambda status: APP_NAME in status.apps)

    status = juju.status()
    assert APP_NAME in status.apps
    # Should be waiting for backend services
    assert status.apps[APP_NAME].is_waiting


def test_productpage_with_backends(juju, charm, resources):
    """Test productpage becomes active when connected to backend services."""
    # Deploy backend services from Charmhub
    juju.deploy("bookinfo-details-k8s", channel="latest/stable")
    juju.deploy("bookinfo-reviews-k8s", channel="latest/stable")

    # Integrate productpage with backend services using correct endpoints
    juju.integrate(f"{APP_NAME}:details", "bookinfo-details-k8s:details")
    juju.integrate(f"{APP_NAME}:reviews", "bookinfo-reviews-k8s:reviews")

    # Wait for all services to become active
    juju.wait(jubilant.all_active)

    status = juju.status()
    assert status.apps[APP_NAME].is_active
    assert status.apps["bookinfo-details-k8s"].is_active
    assert status.apps["bookinfo-reviews-k8s"].is_active


def test_productpage_service_running(juju, charm, resources):
    """Test that the productpage service is properly running."""
    status = juju.status()
    unit_name = f"{APP_NAME}/0"

    assert status.apps[APP_NAME].units[unit_name].is_active


def test_productpage_health_endpoint(juju, charm, resources):
    """Test productpage service health endpoint returns 200."""
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

    assert result.strip() == "200"


def test_productpage_isbn_content(juju, charm, resources):
    """Test productpage displays correct ISBN from details service."""
    result = juju.cli(
        "exec",
        "--unit",
        f"{APP_NAME}/0",
        "--",
        "curl",
        "-s",
        "http://localhost:9080/productpage?u=normal",
    )

    # Strict check for specific ISBN number
    assert "1234567890" in result


def test_productpage_review_content(juju, charm, resources):
    """Test productpage displays correct review from reviews service."""
    result = juju.cli(
        "exec",
        "--unit",
        f"{APP_NAME}/0",
        "--",
        "curl",
        "-s",
        "http://localhost:9080/productpage?u=normal",
    )

    # Strict check for specific review text
    assert (
        "An extremely entertaining play by Shakespeare. The slapstick humour is refreshing!"
        in result
    )
