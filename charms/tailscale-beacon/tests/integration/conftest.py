# Copyright 2026 Canonical Ltd.
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

CHARM_DIR = pathlib.Path(__file__).parents[2]  # The tailscale-beacon charm root.
CONFIG_CHARM_DIR = CHARM_DIR.parent / "tailscale-config"  # The tailscale-config charm root.

# The charm packs for multiple platforms; pin the base used by the integration
# tests so it matches the principal `ubuntu` application they attach to.
CHARM_BASE = "24.04"


def _pack(charm_dir: pathlib.Path, base: str) -> pathlib.Path:
    """Pack ``charm_dir`` and return the ``.charm`` built for ``base``."""
    logger.info("Packing charm in %s", charm_dir)
    subprocess.run(["charmcraft", "pack"], cwd=charm_dir, check=True)
    charms = list(charm_dir.glob(f"*{base}*.charm"))
    assert charms, f"No charm for base {base} was packed in {charm_dir}"
    assert len(charms) == 1, f"Found more than one charm for base {base}: {charms}"
    return charms[0].resolve()


def _pack_single(charm_dir: pathlib.Path) -> pathlib.Path:
    """Pack ``charm_dir`` and return its single resulting ``.charm`` path."""
    logger.info("Packing charm in %s", charm_dir)
    subprocess.run(["charmcraft", "pack"], cwd=charm_dir, check=True)
    charms = list(charm_dir.glob("*.charm"))
    assert charms, f"No charm was packed in {charm_dir}"
    assert len(charms) == 1, f"Found more than one charm {charms}"
    return charms[0].resolve()


@pytest.fixture(scope="session")
def charm() -> pathlib.Path:
    """Return the path of the charm under test.

    Packs the tailscale-beacon charm with ``charmcraft pack``.
    """
    return _pack(CHARM_DIR, CHARM_BASE)


@pytest.fixture(scope="session")
def config_charm() -> pathlib.Path:
    """Return the path of the tailscale-config charm.

    Packs the tailscale-config charm with ``charmcraft pack``, unless
    ``CONFIG_CHARM_PATH`` points at a pre-packed ``.charm`` file.
    """
    charm = os.environ.get("CONFIG_CHARM_PATH")
    if charm:
        path = pathlib.Path(charm).resolve()
        assert path.is_file(), f"{path} is not a file"
        return path
    return _pack_single(CONFIG_CHARM_DIR)


@pytest.fixture(scope="session")
def tailscale_credentials() -> dict[str, str]:
    """Return real Tailscale root OAuth client credentials from the environment.

    tailscale-config mints a scoped per-relation credential from this root
    OAuth client, so the relation flow needs live credentials. Skips the test
    when ``TAILSCALE_CLIENT_ID`` / ``TAILSCALE_CLIENT_SECRET`` are not both set,
    so the suite stays green without them.
    """
    client_id = os.environ.get("TAILSCALE_CLIENT_ID")
    client_secret = os.environ.get("TAILSCALE_CLIENT_SECRET")
    assert client_id and client_secret, "TAILSCALE_CLIENT_ID and TAILSCALE_CLIENT_SECRET must be set"
    return {"client-id": client_id, "client-secret": client_secret}


@pytest.fixture(scope="session")
def auth_key() -> str:
    """Return a Tailscale auth key from the environment.

    The key must be reusable, because it is used to join more than one machine
    to the tailnet, and must permit any tags the key itself requires. The test
    fails (rather than skips) when ``TAILSCALE_TEST_AUTH_KEY`` is unset.
    """
    key = os.environ.get("TAILSCALE_TEST_AUTH_KEY")
    assert key, "TAILSCALE_TEST_AUTH_KEY must be set"
    return key
