# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.


import functools
import logging
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


class Store(defaultdict):
    def __init__(self):
        super(Store, self).__init__(Store)

    def __getattr__(self, key):
        """Override __getattr__ so dot syntax works on keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        """Override __setattr__ so dot syntax works on keys."""
        self[key] = value


store = Store()


def timed_memoizer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fname = func.__qualname__
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        return ret

    return wrapper


@timed_memoizer
async def clone_repo_from_branch(repo_url: str, branch: str, clone_root: Path, name: str) -> Path:
    """Clone a specific branch of a repo into a named subfolder under `clone_root`."""
    clone_path = clone_root / name

    if clone_path.exists():
        shutil.rmtree(clone_path)

    subprocess.check_call(
        ["git", "clone", "-b", branch, "--depth", "1", repo_url, str(clone_path)]
    )
    return clone_path


# We pull oauth proxy manually from this fork until https://github.com/canonical/oauth2-proxy-k8s-operator/issues/72 is fixed
@pytest.fixture(scope="module")
@timed_memoizer
async def oauth2_proxy_charm(ops_test: OpsTest):
    repo_url = "https://github.com/IbraAoad/oauth2-proxy-k8s-operator.git"
    branch = "patch-1"
    name = "oauth2-proxy-k8s-operator"

    clone_path = await clone_repo_from_branch(repo_url, branch, ops_test.tmp_path, name)

    count = 0
    while True:
        try:
            charm = await ops_test.build_charm(clone_path, verbosity="debug")
            return charm
        except RuntimeError:
            logger.warning("Failed to build oauth2-proxy. Trying again!")
            count += 1

            if count == 3:
                raise
