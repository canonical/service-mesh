# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library and the pytest-jubilant plugin.
# See https://documentation.ubuntu.com/ops/latest/howto/write-integration-tests-for-a-charm/
#
# pytest-jubilant provides a module-scoped `juju` fixture that creates a temporary Juju model.
# The `charm`, `dummy_charm`, and `tailscale_credentials` fixtures are defined in conftest.py.

import logging
import pathlib

import jubilant
import pytest

logger = logging.getLogger(__name__)

APP = "tailscale-config"
REQUIRER_APP = "dummy-requirer"


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the workloadless charm under test and check it goes active."""
    juju.deploy(charm, app=APP)

    # The charm blocks until it has a valid backend and a root credential, so
    # mint a fake root-credential secret, grant it to the app, and configure it.
    secret_uri = juju.add_secret(
        "tailscale-config-root-credential",
        {"credential": "fake-root-credential"},
    )
    juju.grant_secret(secret_uri, APP)
    juju.config(APP, {"backend": "tailscale", "root-credential": secret_uri})

    juju.wait(jubilant.all_active)


def test_credentials_flow(
    charm: pathlib.Path,
    dummy_charm: pathlib.Path,
    tailscale_credentials: dict[str, str],
    juju: jubilant.Juju,
):
    """End-to-end: mint a real credential and prove the requirer can use it.

    Deploys tailscale-config with real root OAuth client credentials, deploys a
    dummy requirer, relates them, and waits for both to go active. The dummy
    requirer reaches ActiveStatus only if the minted credential authenticates
    against the live Tailscale API, so `all_active` verifies the full flow.

    Skipped unless TAILSCALE_CLIENT_ID / TAILSCALE_CLIENT_SECRET are set (see
    the `tailscale_credentials` fixture).
    """
    juju.deploy(dummy_charm, app=REQUIRER_APP)

    # Provide the real root OAuth client credentials as a granted user secret.
    secret_uri = juju.add_secret("valid-tailscale-config-root-credential", tailscale_credentials)
    juju.grant_secret(secret_uri, APP)
    juju.config(APP, {"backend": "tailscale", "root-credential": secret_uri})

    juju.integrate(f"{APP}:tailscale-credentials", f"{REQUIRER_APP}:tailscale-credentials")

    juju.wait(jubilant.all_active)
