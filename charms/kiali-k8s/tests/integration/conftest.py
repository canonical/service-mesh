# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
async def charm_under_test(ops_test: OpsTest):
    if charm_file := os.environ.get("CHARM_PATH"):
        return Path(charm_file)

    return await ops_test.build_charm(".", verbosity="debug")

