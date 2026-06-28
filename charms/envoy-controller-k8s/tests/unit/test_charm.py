# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Status-model and lifecycle regression tests for the controller charm."""

from unittest.mock import patch

import httpx
import ops
import pytest
import scenario
from conftest import make_state
from lightkube import ApiError

from charm import EnvoyControllerCharm


def _api_error(code: int) -> ApiError:
    request = httpx.Request("GET", "http://localhost")
    response = httpx.Response(code, json={"message": "x", "code": code}, request=request)
    return ApiError(request=request, response=response)


def test_blocked_without_trust(ctx, mock_lightkube_client):
    # GIVEN a trusted-cluster probe that is denied (charm not run with --trust)
    mock_lightkube_client.list.side_effect = _api_error(403)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it blocks telling the operator exactly how to fix it
    assert state_out.unit_status == ops.BlockedStatus(
        "Trust not granted. Run 'juju trust envoy-controller-k8s'"
    )


def test_waiting_without_pebble(ctx):
    # GIVEN the workload containers are not yet reachable
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state(can_connect=False))
    # THEN it waits for Pebble
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for Pebble (envoy-gateway container)"
    )


def test_active_when_all_preconditions_met(ctx, krm_mocks):
    # GIVEN trust and connected containers
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it is active
    assert state_out.unit_status == ops.ActiveStatus()


def test_waiting_when_controller_health_check_fails(ctx, krm_mocks):
    # GIVEN the envoy-gateway readiness check is failing (e.g. crash-looping)
    failing = frozenset(
        {
            scenario.CheckInfo(
                name="readiness",
                level=ops.pebble.CheckLevel.READY,
                status=ops.pebble.CheckStatus.DOWN,
            )
        }
    )
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state(gateway_checks=failing))
    # THEN it reports waiting (transient — Pebble auto-restarts), not active
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for envoy-gateway controller to become healthy"
    )


def test_unexpected_api_error_is_not_swallowed(ctx, mock_lightkube_client):
    # GIVEN the trust probe fails with a non-auth error (API unreachable, 500, ...)
    mock_lightkube_client.list.side_effect = _api_error(500)
    # WHEN trust is evaluated
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        # THEN the error surfaces rather than being misreported as "untrusted"
        with pytest.raises(ApiError):
            _ = mgr.charm._trusted
        # Reset so the manager's implicit exit-time reconcile sees a healthy client.
        mock_lightkube_client.list.side_effect = None


def test_remove_deletes_cluster_resources_only_when_last_unit_leaves(ctx):
    # GIVEN this is the final unit of the application
    with patch.object(EnvoyControllerCharm, "_webhook_krm") as webhook, patch.object(
        EnvoyControllerCharm, "_control_plane_service_krm"
    ) as service:
        # WHEN the unit is removed
        ctx.run(ctx.on.remove(), make_state(planned_units=0))
    # THEN the app-scoped ExtProc webhook and control-plane Service are cleaned up
    webhook.return_value.delete.assert_called_once()
    service.return_value.delete.assert_called_once()


def test_remove_keeps_cluster_resources_on_scale_down(ctx):
    # GIVEN peer units of the application remain
    with patch.object(EnvoyControllerCharm, "_webhook_krm") as webhook, patch.object(
        EnvoyControllerCharm, "_control_plane_service_krm"
    ) as service:
        # WHEN this unit is removed
        ctx.run(ctx.on.remove(), make_state(planned_units=1))
    # THEN the shared cluster resources are left in place for the surviving units
    webhook.return_value.delete.assert_not_called()
    service.return_value.delete.assert_not_called()
