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


@pytest.fixture(scope="session")
def charm() -> pathlib.Path:
    """Return the path of the charm under test.

    Packs the tailscale-beacon charm with ``charmcraft pack``, unless
    ``CHARM_PATH`` points at a pre-packed ``.charm`` file.
    """
    charm = os.environ.get("CHARM_PATH")
    if charm:
        path = pathlib.Path(charm).resolve()
        assert path.is_file(), f"{path} is not a file"
        return path
    return _pack(CHARM_DIR, CHARM_BASE)


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
