# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
import scenario
from lightkube.resources.autoscaling_v2 import HorizontalPodAutoscaler
from ops import ActiveStatus

from charm import IstioBeaconCharm


# TODO: introduce mocks needed for testing model-on-mesh
def test_relation_changed_status():
    ctx = scenario.Context(IstioBeaconCharm)
    out = ctx.run(ctx.on.start(), scenario.State())
    assert out.unit_status.name == "unknown"


@pytest.mark.parametrize("planned_units", [1, 3, 5])
@patch.object(IstioBeaconCharm, "_is_waypoint_deployment_ready")
@patch.object(IstioBeaconCharm, "_put_charm_on_mesh")
@patch.object(IstioBeaconCharm, "_get_waypoint_resource_manager")
@patch.object(IstioBeaconCharm, "_setup_proxy_pebble_service")
def test_sync_all_triggers_hpa_reconcile(
    mock_setup_proxy_pebble_service,
    mock_get_waypoint_resource_manager,
    mock_put_charm_on_mesh,
    mock_is_waypoint_deployment_ready,
    istio_beacon_context,
    planned_units,
):
    """Assert that HPA reconciliation is invoked in _sync_waypoint_resources.

    Also check if the HPA spec contains the right number of replicas.
    """
    mock_waypoint_resource_manager = mock_get_waypoint_resource_manager.return_value
    state = scenario.State(relations=[], leader=True, planned_units=planned_units)

    result = istio_beacon_context.run(istio_beacon_context.on.config_changed(), state)

    mock_get_waypoint_resource_manager.assert_called_once()
    mock_waypoint_resource_manager.reconcile.assert_called_once()
    resources = mock_waypoint_resource_manager.reconcile.call_args.args[0]

    # we expect exactly two resources: the Waypoint and the HPA
    assert len(resources) == 2

    # filter out only the HPA object
    hpas = [r for r in resources if isinstance(r, HorizontalPodAutoscaler)]
    assert len(hpas) == 1

    hpa = hpas[0]
    assert hpa.spec.minReplicas == planned_units  # pyright: ignore[reportOptionalMemberAccess]
    assert hpa.spec.maxReplicas == planned_units  # pyright: ignore[reportOptionalMemberAccess]

    assert isinstance(result.unit_status, ActiveStatus)


@pytest.mark.parametrize(
    "planned_units, call_count",
    [
        (0, 1),  # last unit → we should clean up
        (1, 0),  # still 1 (scale-down to 1) → skip
        (2, 0),  # >1 (scale-down to >1) → skip
    ],
)
@patch.object(IstioBeaconCharm, "_get_waypoint_resource_manager")
@patch.object(IstioBeaconCharm, "_get_authorization_policy_resource_manager")
def test_on_remove_deletes_hpa_only_when_last_unit(
    mock_get_authorization_policy_resource_manager,
    mock_get_waypoint_resource_manager,
    istio_beacon_context,
    planned_units,
    call_count,
):
    """Assert that the KRM's (waypoint and authorization policy) delete method is called only when the last unit is about to be removed.

    Also test the vice-versa is true, that the delete methods from KRM is not called when scaling down to non-zero units.
    """
    state = scenario.State(
        relations=[],
        leader=False,
        planned_units=planned_units,
    )

    istio_beacon_context.run(istio_beacon_context.on.remove(), state)

    mock_waypoint_resource_manager = mock_get_waypoint_resource_manager.return_value
    assert mock_waypoint_resource_manager.delete.call_count == call_count

    mock_authorization_policy_resource_manager = mock_get_authorization_policy_resource_manager.return_value
    assert mock_authorization_policy_resource_manager.delete.call_count == call_count
