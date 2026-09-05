# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
import scenario

from charm import TailscaleBeaconCharm
from tailscale import TailscaleStatus


@pytest.fixture()
def ctx():
    return scenario.Context(TailscaleBeaconCharm)


@pytest.fixture(autouse=True)
def tailscale():
    with patch("charm.Tailscale", autospec=True) as tailscale_class:
        instance = tailscale_class.return_value
        instance.snap_installed = True
        instance.configuration_is_current.return_value = False
        instance.has_other_units = False
        instance.status.return_value = TailscaleStatus(
            backend_state="Running",
            dns_name="machine.tailnet.ts.net",
            tailnet_name="tailnet.ts.net",
        )
        yield instance


@pytest.fixture()
def manual_secret():
    return scenario.Secret(
        tracked_content={"auth-key": "tskey-auth-test"},
        latest_content={"auth-key": "tskey-auth-test"},
        owner="app",
    )


@pytest.fixture()
def manual_state(manual_secret):
    return scenario.State(
        config={"credentials": manual_secret.id},
        secrets=[manual_secret],
        relations=[scenario.SubordinateRelation("juju-info")],
    )


@pytest.fixture()
def command():
    with patch("tailscale.subprocess.run", autospec=True) as run:
        result = MagicMock(returncode=0, stdout="")
        run.return_value = result
        yield run
