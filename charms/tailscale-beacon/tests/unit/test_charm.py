# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess

import ops
import pytest
import scenario

from tailscale import TailscaleStatus


def test_reconcile_installs_and_connects(ctx, manual_state, tailscale):
    output = ctx.run(ctx.on.config_changed(), manual_state)
    tailscale.register_unit.assert_called_once()
    tailscale.ensure_snap.assert_called_once_with("1/stable")
    credentials = tailscale.up.call_args.args[0]
    assert credentials.auth_key == "tskey-auth-test"
    assert output.unit_status == ops.ActiveStatus("Connected as machine.tailnet.ts.net")


def test_no_credentials_blocks(ctx, tailscale):
    state = scenario.State(relations=[scenario.SubordinateRelation("juju-info")])
    output = ctx.run(ctx.on.config_changed(), state)
    tailscale.up.assert_not_called()
    assert output.unit_status.name == "blocked"
    assert output.unit_status.message.startswith("No credentials configured")


def test_waiting_for_relation_data(ctx):
    relation = scenario.Relation("tailscale-credentials")
    state = scenario.State(relations=[scenario.SubordinateRelation("juju-info"), relation])
    output = ctx.run(ctx.on.relation_changed(relation), state)
    assert output.unit_status == ops.WaitingStatus(
        "Waiting for credentials from tailscale-config."
    )


def test_needs_machine_auth_blocks(ctx, manual_state, tailscale):
    tailscale.status.return_value = TailscaleStatus(backend_state="NeedsMachineAuth")
    output = ctx.run(ctx.on.collect_unit_status(), manual_state)
    assert output.unit_status == ops.BlockedStatus(
        "Tailnet device requires administrator approval"
    )


def test_last_unit_disconnects(ctx, manual_state, tailscale):
    ctx.run(ctx.on.stop(), manual_state)
    tailscale.disconnect.assert_called_once()
    tailscale.unregister_unit.assert_called_once()
    tailscale.remove_snap.assert_not_called()


def test_non_final_unit_leaves_daemon_running(ctx, manual_state, tailscale):
    tailscale.has_other_units = True
    ctx.run(ctx.on.stop(), manual_state)
    tailscale.disconnect.assert_not_called()
    tailscale.unregister_unit.assert_called_once()


def test_last_unit_can_remove_snap(ctx, manual_state, tailscale):
    state = scenario.State(
        config={**manual_state.config, "remove-snap": True},
        secrets=manual_state.secrets,
        relations=manual_state.relations,
    )
    ctx.run(ctx.on.stop(), state)
    tailscale.disconnect.assert_called_once()
    tailscale.remove_snap.assert_called_once()


def test_removing_credentials_disconnects_managed_session(ctx, tailscale):
    state = scenario.State(relations=[scenario.SubordinateRelation("juju-info")])
    ctx.run(ctx.on.config_changed(), state)
    tailscale.disconnect.assert_called_once()


def test_current_configuration_is_not_reapplied(ctx, manual_state, tailscale):
    tailscale.configuration_is_current.return_value = True
    ctx.run(ctx.on.config_changed(), manual_state)
    tailscale.ensure_snap.assert_not_called()
    tailscale.up.assert_not_called()


def test_failed_last_unit_disconnect_is_retried(ctx, manual_state, tailscale):
    tailscale.disconnect.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["tailscale", "down"]
    )
    with pytest.raises(Exception):
        ctx.run(ctx.on.stop(), manual_state)
    tailscale.unregister_unit.assert_not_called()
