# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

from ops import testing

from charm import TailscaleConfigCharm
from tailscale_config import CharmState

ROOT_CREDENTIAL_URI = "secret:cvh7kruupa1s46bqvuig"


def test_active_status():
    """A valid backend with a root credential set reports active."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()


def test_blocked_without_root_credential():
    """Without a root credential the charm blocks."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(config={"backend": "tailscale"})

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "root-credential" in state_out.unit_status.message


def test_blocked_on_invalid_backend():
    """An unrecognized backend blocks, even with a root credential set."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "bogus", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "bogus" in state_out.unit_status.message


def test_collect_state_normalizes_empty_login_server():
    """An empty login-server config collapses to None."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={
            "backend": "headscale",
            "login-server": "",
            "root-credential": ROOT_CREDENTIAL_URI,
        },
    )

    # Act:
    with ctx(ctx.on.collect_unit_status(), state_in) as manager:
        state = manager.charm._collect_state()

    # Assert:
    assert state == CharmState(
        backend="headscale",
        root_credential=ROOT_CREDENTIAL_URI,
        login_server=None,
    )
