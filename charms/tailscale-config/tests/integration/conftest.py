# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library and the pytest-jubilant plugin.
# See https://documentation.ubuntu.com/ops/latest/howto/write-integration-tests-for-a-charm/

import logging
import os
import pathlib
import subprocess

import pytest

logger = logging.getLogger(__name__)

CHARM_DIR = pathlib.Path(__file__).parents[2]  # The tailscale-config charm root.
DUMMY_REQUIRER_DIR = pathlib.Path(__file__).parent / "dummy-requirer"


def _pack(charm_dir: pathlib.Path) -> pathlib.Path:
    """Pack the charm in ``charm_dir`` and return the resulting ``.charm`` path."""
    logger.info("Packing charm in %s", charm_dir)
    subprocess.run(["charmcraft", "pack"], cwd=charm_dir, check=True)
    charms = list(charm_dir.glob("*.charm"))
    assert charms, f"No charm was packed in {charm_dir}"
    assert len(charms) == 1, f"Found more than one charm {charms}"
    return charms[0].resolve()


@pytest.fixture(scope="session")
def charm():
    """Return the path of the charm under test.

    Packs the tailscale-config charm with ``charmcraft pack``, unless
    ``CHARM_PATH`` points at a pre-packed ``.charm`` file.
    """
    charm = os.environ.get("CHARM_PATH")
    if charm:
        path = pathlib.Path(charm).resolve()
        assert path.is_file(), f"{path} is not a file"
        return path
    return _pack(CHARM_DIR)


@pytest.fixture(scope="session")
def dummy_charm():
    """Pack and return the path of the dummy requirer charm.

    Packs ``tests/integration/dummy-requirer`` with ``charmcraft pack``. The
    resulting ``.charm`` is reused across the session.
    """
    return _pack(DUMMY_REQUIRER_DIR)


@pytest.fixture(scope="session")
def tailscale_credentials() -> dict[str, str]:
    """Return real Tailscale root OAuth client credentials from the environment.

    Skips the test when ``TAILSCALE_CLIENT_ID`` / ``TAILSCALE_CLIENT_SECRET``
    are not both set, so the suite stays green without live credentials.
    """
    client_id = os.environ.get("TAILSCALE_CLIENT_ID")
    client_secret = os.environ.get("TAILSCALE_CLIENT_SECRET")
    if not client_id or not client_secret:
        pytest.skip("TAILSCALE_CLIENT_ID and TAILSCALE_CLIENT_SECRET must be set")
    return {"client-id": client_id, "client-secret": client_secret}
