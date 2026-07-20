# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library and the pytest-jubilant plugin.
# See https://documentation.ubuntu.com/ops/latest/howto/write-integration-tests-for-a-charm/
#
# pytest-jubilant provides a module-scoped `juju` fixture that creates a temporary Juju model.
# The `charm` fixture is defined in conftest.py.

import logging
import pathlib

import jubilant
import pytest

logger = logging.getLogger(__name__)


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the workloadless charm under test and check it goes active."""
    app = "tailscale-config"
    juju.deploy(charm, app=app)

    # The charm blocks until it has a valid backend and a root credential, so
    # mint a fake root-credential secret, grant it to the app, and configure it.
    secret_uri = juju.add_secret(
        "tailscale-config-root-credential",
        {"credential": "fake-root-credential"},
    )
    juju.grant_secret(secret_uri, app)
    juju.config(app, {"backend": "tailscale", "root-credential": secret_uri})

    juju.wait(jubilant.all_active)
