# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Status-model and reconcile regression tests for the ingress charm."""

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import ops
import pytest
from conftest import make_state, ready_ingress
from lightkube import ApiError

import charm


def _api_error(code: int) -> ApiError:
    request = httpx.Request("GET", "http://localhost")
    response = httpx.Response(code, json={"message": "x", "code": code}, request=request)
    return ApiError(request=request, response=response)


def test_blocked_without_trust(ctx, mock_lightkube_client):
    # GIVEN a trust probe that is denied (charm not run with --trust)
    mock_lightkube_client.list.side_effect = _api_error(403)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it blocks telling the operator exactly how to fix it
    assert state_out.unit_status == ops.BlockedStatus(
        "Trust not granted — run 'juju trust envoy-ingress-k8s'"
    )


def test_waiting_without_controller(ctx, gateway_class_pending):
    # GIVEN trust but the controller has not yet Accepted the GatewayClass
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it waits for the controller rather than writing Gateway resources
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for GatewayClass controller to become available"
    )


def test_active_reports_serving_address(ctx, gateway_class_accepted, krm_mocks):
    # GIVEN trust, an Accepted GatewayClass, and a resolvable gateway address
    # (external_hostname config short-circuits the Gateway-status LB lookup)
    state_out = ctx.run(
        ctx.on.config_changed(),
        make_state(config={"external_hostname": "ingress.example.com"}),
    )
    # THEN it is active and reports where it is serving (mirrors istio-ingress)
    assert state_out.unit_status == ops.ActiveStatus("Serving at ingress.example.com")


def test_waiting_without_gateway_address(ctx, gateway_class_accepted, krm_mocks):
    # GIVEN trust and an Accepted GatewayClass but the Gateway has no address yet
    # (no external_hostname config and no LB address in the Gateway status)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it waits for the address rather than reporting a bare/None serving URL
    assert state_out.unit_status == ops.WaitingStatus("Waiting for gateway address assignment")


def test_unexpected_api_error_is_not_swallowed(ctx, mock_lightkube_client):
    # GIVEN the trust probe fails with a non-auth error (API unreachable, 500, ...)
    mock_lightkube_client.list.side_effect = _api_error(500)
    # WHEN trust is evaluated
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        # THEN the error surfaces rather than being misreported as "untrusted"
        with pytest.raises(ApiError):
            _ = mgr.charm._trusted
        mock_lightkube_client.list.side_effect = None


def test_route_conflict_blocks_and_drops_all_contested_routes(
    ctx, gateway_class_accepted, krm_mocks
):
    # GIVEN two different apps whose generated default paths collide
    with ready_ingress(("b-c", "a"), ("c", "a-b")), patch.object(
        charm.IngressPerAppProvider, "wipe_ingress_data"
    ), patch.object(charm.IngressPerAppProvider, "publish_url"):
        # WHEN the charm reconciles
        state_out = ctx.run(ctx.on.config_changed(), make_state())
        # THEN no HTTPRoute is created for either contesting app
        (objs,), _ = krm_mocks.httproute.reconcile.call_args
        assert objs == []
    # AND the charm blocks reporting the conflict
    assert state_out.unit_status == ops.BlockedStatus(
        "Route conflict detected; check the logs for details"
    )


def test_https_listener_appears_only_with_certificates(
    ctx, gateway_class_accepted, krm_mocks, certs_ready
):
    # GIVEN issued certificates and a certificates relation
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), make_state(certificates=True))
    # THEN the Gateway gains an HTTPS listener referencing the managed TLS Secret
    (objs,), _ = krm_mocks.gateway.reconcile.call_args
    listeners = objs[0].spec["listeners"]
    assert [listener["protocol"] for listener in listeners] == ["HTTP", "HTTPS"]
    https = next(listener for listener in listeners if listener["protocol"] == "HTTPS")
    assert https["tls"]["certificateRefs"][0]["name"] == "envoy-ingress-k8s-tls"


def test_security_policy_toggles_with_forward_auth(
    ctx, gateway_class_accepted, krm_mocks
):
    # GIVEN a forward-auth provider advertising a decisions address
    info = SimpleNamespace(decisions_address="auth-svc")
    with patch.object(
        charm.ForwardAuthRequirer, "get_provider_info", return_value=info
    ):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state(forward_auth=True))
    # THEN a SecurityPolicy with extAuth pointing at the provider is created
    (objs,), _ = krm_mocks.security_policy.reconcile.call_args
    assert objs[0].spec["extAuth"]["http"]["backendRefs"][0]["name"] == "auth-svc"

    # GIVEN the provider goes away
    with patch.object(
        charm.ForwardAuthRequirer, "get_provider_info", return_value=None
    ):
        # WHEN the charm reconciles again
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN the stale SecurityPolicy is deleted
    krm_mocks.security_policy.delete.assert_called_once()


def test_remove_deletes_resources_only_when_last_unit_leaves(ctx, krm_mocks):
    # GIVEN this is the final unit of the application
    # WHEN the unit is removed
    ctx.run(ctx.on.remove(), make_state(planned_units=0))
    # THEN the cluster-scoped GatewayClass is cleaned up
    krm_mocks.gateway_class.delete.assert_called_once()


def test_remove_keeps_resources_on_scale_down(ctx, krm_mocks):
    # GIVEN peer units of the application remain
    # WHEN this unit is removed
    ctx.run(ctx.on.remove(), make_state(planned_units=1))
    # THEN shared resources are left in place
    krm_mocks.gateway_class.delete.assert_not_called()
