# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

from ops import testing

from charm import TailscaleConfigCharm


def test_active_status():
    """Test that the workloadless charm reports active status."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State()

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()
