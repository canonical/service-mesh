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
from lightkube.models.meta_v1 import ObjectMeta

import charm
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


def test_blocked_when_foreign_gateway_class_exists(ctx, krm_mocks):
    # GIVEN a pre-existing "envoy" GatewayClass this controller does not own (a second
    # controller or a non-Juju install) — the class is a cluster-wide singleton
    krm_mocks.foreign_owner.return_value = "other-model-envoy-controller-k8s"
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it blocks (concise; detail is in the logs) and never overwrites the foreign class
    assert state_out.unit_status == ops.BlockedStatus("Existing 'envoy' GatewayClass; see logs")
    krm_mocks.gateway_class.reconcile.assert_not_called()


def test_foreign_gateway_class_owner_detection(ctx, mock_lightkube_client):
    # Distinguishes "the class we manage" from a foreign one using the KRM instance label
    # stamped on resources this app manages — no ownership bookkeeping needed.
    with ctx(ctx.on.config_changed(), make_state()) as mgr:
        c = mgr.charm
        mine = charm.create_charm_default_labels(
            c.app.name, c.model.name, scope=charm.GATEWAY_CLASS_SCOPE
        )
        # our stamp -> we own it
        mock_lightkube_client.get.return_value = charm.GatewayClass(
            metadata=ObjectMeta(name=charm.GATEWAY_CLASS_NAME, labels=dict(mine))
        )
        assert c._foreign_gateway_class_owner() is None
        # another controller's stamp -> foreign
        mock_lightkube_client.get.return_value = charm.GatewayClass(
            metadata=ObjectMeta(
                name=charm.GATEWAY_CLASS_NAME,
                labels={charm.GATEWAY_CLASS_OWNER_LABEL: "other-model-other-app"},
            )
        )
        assert c._foreign_gateway_class_owner() == "other-model-other-app"
        # no stamp at all (Helm/kubectl) -> foreign, reported as unmanaged
        mock_lightkube_client.get.return_value = charm.GatewayClass(
            metadata=ObjectMeta(name=charm.GATEWAY_CLASS_NAME)
        )
        assert c._foreign_gateway_class_owner() == "<unmanaged>"
        # absent -> free to create
        mock_lightkube_client.get.side_effect = _api_error(404)
        assert c._foreign_gateway_class_owner() is None


def test_waiting_when_controller_health_check_fails(ctx, krm_mocks):
    # GIVEN the envoy-gateway readiness check is failing (controller alive but not serving)
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
    # THEN it reports waiting, not active. Note: readiness is NOT restart-wired (only
    # liveness is), so a sustained readiness failure stays in waiting rather than
    # restart-looping.
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


def test_maintenance_while_crds_not_established(ctx, krm_mocks):
    # GIVEN the CRDs are applied but not yet Established, so reconcile halts before
    # the controller service is added to the plan
    with patch.object(EnvoyControllerCharm, "_crds_established", return_value=False):
        # WHEN the charm reconciles and status is collected
        state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it reports maintenance rather than falsely reporting Active
    assert state_out.unit_status == ops.MaintenanceStatus("Setting up Envoy Gateway control plane")


def test_remove_deletes_cluster_resources_only_when_last_unit_leaves(ctx):
    # GIVEN this is the final unit of the application
    with patch.object(
        EnvoyControllerCharm, "_control_plane_service_krm"
    ) as service, patch.object(
        EnvoyControllerCharm, "_envoy_proxy_krm"
    ) as proxy, patch.object(EnvoyControllerCharm, "_gateway_class_krm") as gateway_class:
        # WHEN the unit is removed
        ctx.run(ctx.on.remove(), make_state(planned_units=0))
    # THEN the control-plane Service, default EnvoyProxy and shared GatewayClass are cleaned up
    service.return_value.delete.assert_called_once()
    proxy.return_value.delete.assert_called_once()
    gateway_class.return_value.delete.assert_called_once()


def test_remove_keeps_cluster_resources_on_scale_down(ctx):
    # GIVEN peer units of the application remain
    with patch.object(
        EnvoyControllerCharm, "_control_plane_service_krm"
    ) as service, patch.object(
        EnvoyControllerCharm, "_envoy_proxy_krm"
    ) as proxy, patch.object(EnvoyControllerCharm, "_gateway_class_krm") as gateway_class:
        # WHEN this unit is removed
        ctx.run(ctx.on.remove(), make_state(planned_units=1))
    # THEN the shared cluster resources are left in place for the surviving units
    service.return_value.delete.assert_not_called()
    proxy.return_value.delete.assert_not_called()
    gateway_class.return_value.delete.assert_not_called()
