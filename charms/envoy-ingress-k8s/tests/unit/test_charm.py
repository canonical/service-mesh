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


def test_strip_prefix_adds_urlrewrite_filter(ctx, gateway_class_accepted, krm_mocks):
    # GIVEN a requirer that asked for prefix stripping (the normal IPA case)
    with ready_ingress(("app", "model", 8080, True)), patch.object(
        charm.IngressPerAppProvider, "publish_url"
    ), patch.object(charm.IngressPerAppProvider, "wipe_ingress_data"):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN the HTTPRoute carries a URLRewrite filter rewriting the prefix to "/"
    # so the backend sees "/..." not "/model-app/..." (without it: 404s)
    (objs,), _ = krm_mocks.httproute.reconcile.call_args
    assert len(objs) == 1
    filters = objs[0].spec["rules"][0]["filters"]
    assert filters == [
        {
            "type": "URLRewrite",
            "urlRewrite": {"path": {"type": "ReplacePrefixMatch", "replacePrefixMatch": "/"}},
        }
    ]


def test_no_strip_prefix_has_no_filter(ctx, gateway_class_accepted, krm_mocks):
    # GIVEN a requirer that did not ask for prefix stripping
    with ready_ingress(("app", "model", 8080, False)), patch.object(
        charm.IngressPerAppProvider, "publish_url"
    ), patch.object(charm.IngressPerAppProvider, "wipe_ingress_data"):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN the HTTPRoute carries no rewrite filter
    (objs,), _ = krm_mocks.httproute.reconcile.call_args
    assert objs[0].spec["rules"][0]["filters"] == []


def test_http_route_attaches_to_http_listener_without_tls(
    ctx, gateway_class_accepted, krm_mocks
):
    # GIVEN no certificates relation (plaintext ingress)
    with ready_ingress(("app", "model")), patch.object(
        charm.IngressPerAppProvider, "publish_url"
    ), patch.object(charm.IngressPerAppProvider, "wipe_ingress_data"):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN a single route attaches to the HTTP listener and routes to the backend
    (objs,), _ = krm_mocks.httproute.reconcile.call_args
    assert len(objs) == 1
    assert objs[0].spec["parentRefs"][0]["sectionName"] == charm.HTTP_LISTENER_NAME
    assert objs[0].spec["rules"][0]["backendRefs"][0]["name"] == "app"


def test_route_created_in_backend_namespace_for_cross_model(
    ctx, gateway_class_accepted, krm_mocks
):
    # GIVEN a requirer whose backend lives in a different model (namespace) than the
    # ingress charm — the cross-model (CMR) case
    with ready_ingress(("app", "requirer-model")), patch.object(
        charm.IngressPerAppProvider, "publish_url"
    ), patch.object(charm.IngressPerAppProvider, "wipe_ingress_data"):
        # WHEN the charm reconciles
        with ctx(ctx.on.config_changed(), make_state()) as mgr:
            mgr.run()
            gateway_namespace = mgr.charm.model.name
    # THEN the HTTPRoute is co-located with its backend Service in the requirer's
    # namespace, so the same-namespace backendRef needs no ReferenceGrant ...
    (objs,), _ = krm_mocks.httproute.reconcile.call_args
    assert objs[0].metadata.namespace == "requirer-model"
    assert objs[0].spec["rules"][0]["backendRefs"][0]["namespace"] == "requirer-model"
    # ... while it still attaches to the Gateway in the ingress charm's namespace
    assert objs[0].spec["parentRefs"][0]["namespace"] == gateway_namespace


def test_tls_routes_backend_to_https_and_redirects_http(
    ctx, gateway_class_accepted, krm_mocks, certs_ready
):
    # GIVEN issued certificates (HTTPS ingress) — without per-listener routing,
    # HTTPS would 404 because routes only ever attached to the HTTP listener (C2)
    with ready_ingress(("app", "model")), patch.object(
        charm.IngressPerAppProvider, "publish_url"
    ), patch.object(charm.IngressPerAppProvider, "wipe_ingress_data"):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state(certificates=True))
    # THEN the backend route attaches to the HTTPS listener
    (objs,), _ = krm_mocks.httproute.reconcile.call_args
    by_listener = {o.spec["parentRefs"][0]["sectionName"]: o for o in objs}
    assert set(by_listener) == {charm.HTTP_LISTENER_NAME, charm.HTTPS_LISTENER_NAME}
    https_route = by_listener[charm.HTTPS_LISTENER_NAME]
    assert https_route.spec["rules"][0]["backendRefs"][0]["name"] == "app"
    # AND a second route on the HTTP listener redirects plaintext traffic to HTTPS
    http_route = by_listener[charm.HTTP_LISTENER_NAME]
    redirect = http_route.spec["rules"][0]["filters"][0]
    assert redirect == {
        "type": "RequestRedirect",
        "requestRedirect": {"scheme": "https", "statusCode": 301},
    }


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
    # GIVEN a forward-auth provider advertising a decisions URL (not a Service name)
    info = SimpleNamespace(
        decisions_address="http://oauth2-proxy.iam.svc.cluster.local:4180/auth"
    )
    with patch.object(
        charm.ForwardAuthRequirer, "get_provider_info", return_value=info
    ):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state(forward_auth=True))
    # THEN a Backend CR carries the URL's host/port as an FQDN endpoint
    (backends,), _ = krm_mocks.ext_auth_backend.reconcile.call_args
    fqdn = backends[0].spec["endpoints"][0]["fqdn"]
    assert fqdn["hostname"] == "oauth2-proxy.iam.svc.cluster.local"
    assert fqdn["port"] == 4180
    # AND the SecurityPolicy references that Backend (kind: Backend) with the URL path
    (policies,), _ = krm_mocks.security_policy.reconcile.call_args
    ref = policies[0].spec["extAuth"]["http"]["backendRefs"][0]
    assert ref["kind"] == "Backend"
    assert ref["name"] == "envoy-ingress-k8s-ext-auth"
    assert policies[0].spec["extAuth"]["http"]["path"] == "/auth"

    # GIVEN the provider goes away
    with patch.object(
        charm.ForwardAuthRequirer, "get_provider_info", return_value=None
    ):
        # WHEN the charm reconciles again
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN both the stale SecurityPolicy and Backend are deleted
    krm_mocks.security_policy.delete.assert_called_once()
    krm_mocks.ext_auth_backend.delete.assert_called_once()


def test_gateway_references_shared_gateway_class(ctx, gateway_class_accepted, krm_mocks):
    # The ingress does not own the GatewayClass; it only references the shared,
    # controller-owned class by its constant name on every Gateway it creates.
    ctx.run(ctx.on.config_changed(), make_state())
    (objs,), _ = krm_mocks.gateway.reconcile.call_args
    assert objs[0].spec["gatewayClassName"] == charm.GATEWAY_CLASS_NAME


def test_remove_deletes_resources_only_when_last_unit_leaves(ctx, krm_mocks):
    # GIVEN this is the final unit of the application
    # WHEN the unit is removed
    ctx.run(ctx.on.remove(), make_state(planned_units=0))
    # THEN the charm's own resources are cleaned up (the GatewayClass is not ours)
    krm_mocks.gateway.delete.assert_called_once()


def test_remove_keeps_resources_on_scale_down(ctx, krm_mocks):
    # GIVEN peer units of the application remain
    # WHEN this unit is removed
    ctx.run(ctx.on.remove(), make_state(planned_units=1))
    # THEN shared resources are left in place
    krm_mocks.gateway.delete.assert_not_called()
