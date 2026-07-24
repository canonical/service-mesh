# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Status-model and reconcile tests for the tailscale-beacon-k8s charm."""

from types import SimpleNamespace

import httpx
import ops
import pytest
from conftest import make_state, proxy_state, proxy_states, ready_ingress
from lightkube import ApiError

from charm import PROXY_READY_CONDITION


def _api_error(code: int) -> ApiError:
    request = httpx.Request("GET", "http://localhost")
    response = httpx.Response(code, json={"message": "x", "code": code}, request=request)
    return ApiError(request=request, response=response)


def _fake_service(hostname=None, ip=None, condition=None):
    """Build a stand-in Service whose status mimics the operator's writes.

    condition, if given, is a (reason, message) tuple for a ProxyReady condition.
    """
    lb_ingress = []
    if hostname or ip:
        lb_ingress = [SimpleNamespace(hostname=hostname, ip=ip)]
    conditions = []
    if condition is not None:
        conditions = [
            SimpleNamespace(
                type=PROXY_READY_CONDITION, reason=condition[0], message=condition[1]
            )
        ]
    return SimpleNamespace(
        status=SimpleNamespace(
            loadBalancer=SimpleNamespace(ingress=lb_ingress),
            conditions=conditions,
        )
    )


def test_blocked_without_trust(ctx, mock_lightkube_client):
    # GIVEN a trust probe that is denied (charm not run with --trust)
    mock_lightkube_client.list.side_effect = _api_error(403)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it blocks telling the operator exactly how to fix it
    assert state_out.unit_status == ops.BlockedStatus(
        "Trust not granted. Run 'juju trust tailscale-beacon-k8s'"
    )


def test_active_when_idle(ctx):
    # GIVEN trust and no ingress relations
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.update_status(), make_state())
    # THEN it is active with no message (nothing to expose yet)
    assert state_out.unit_status == ops.ActiveStatus()


def test_waiting_when_proxy_pending(ctx, service_krm_mock):
    # GIVEN a related app whose proxy is still coming up
    with ready_ingress(("productpage", "apps")), proxy_states(
        productpage=proxy_state(pending=True, message="provisioning proxy")
    ):
        state_out = ctx.run(
            ctx.on.update_status(), make_state(ingress=1, config={"ready-timeout": 0})
        )
    # THEN it waits with a generic message (app names go to the log, not status)
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for tailnet proxies to become ready"
    )


def test_waiting_status_is_generic_for_multiple_pending(ctx, service_krm_mock):
    # GIVEN several related apps whose proxies are all still coming up
    with ready_ingress(("app-a", "model-a"), ("app-b", "model-b")), proxy_states(
        **{
            "app-a": proxy_state(pending=True, message="provisioning proxy"),
            "app-b": proxy_state(pending=True, message="provisioning proxy"),
        }
    ):
        state_out = ctx.run(
            ctx.on.update_status(), make_state(ingress=2, config={"ready-timeout": 0})
        )
    # THEN the status stays generic; it never singles out or lists app names
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for tailnet proxies to become ready"
    )


def test_pending_apps_are_named_in_the_log(ctx, service_krm_mock, ingress_io, caplog):
    # GIVEN several related apps whose proxies are all still pending
    with ready_ingress(("app-a", "model-a"), ("app-b", "model-b")), proxy_states(
        **{
            "app-a": proxy_state(pending=True, message="provisioning proxy"),
            "app-b": proxy_state(pending=True, message="provisioning proxy"),
        }
    ):
        ctx.run(
            ctx.on.config_changed(), make_state(ingress=2, config={"ready-timeout": 0})
        )
    # THEN the pending apps are named (aggregated) in a single warning log
    warnings = "\n".join(r.message for r in caplog.records if r.levelname == "WARNING")
    assert "app-a" in warnings and "app-b" in warnings


def test_blocked_status_is_generic_on_terminal_error(ctx, service_krm_mock):
    # GIVEN a related app whose proxy has terminally failed
    with ready_ingress(("productpage", "apps")), proxy_states(
        productpage=proxy_state(error=True, message="ProxyFailed: bad config")
    ):
        state_out = ctx.run(
            ctx.on.collect_unit_status(),
            make_state(ingress=1, config={"ready-timeout": 0}),
        )
    # THEN the status is generic (details are logged / raised, not shown here)
    assert state_out.unit_status == ops.BlockedStatus("One or more tailnet proxies failed")


def test_active_reports_tailnet_when_exposed(ctx, service_krm_mock):
    # GIVEN a related app whose proxy is ready on the tailnet
    with ready_ingress(("productpage", "apps")), proxy_states(
        productpage=proxy_state(hostname="productpage.tailnet-abc.ts.net")
    ):
        state_out = ctx.run(ctx.on.update_status(), make_state(ingress=1))
    # THEN it is active and reports the tailnet derived from the MagicDNS name
    assert state_out.unit_status == ops.ActiveStatus(
        "Connected to tailnet tailnet-abc.ts.net"
    )


def test_reconcile_creates_one_service_per_relation(ctx, service_krm_mock):
    # GIVEN two related apps
    with ready_ingress(("app-a", "model-a", 8080), ("app-b", "model-b", 9090)), proxy_states(
        **{
            "app-a": proxy_state(hostname="app-a.ts.net"),
            "app-b": proxy_state(hostname="app-b.ts.net"),
        }
    ):
        ctx.run(ctx.on.config_changed(), make_state(ingress=2))
    # THEN one LoadBalancer Service is reconciled per relation
    service_krm_mock.reconcile.assert_called_once()
    (services,) = service_krm_mock.reconcile.call_args.args
    names = {s.metadata.name for s in services}
    assert names == {"app-a-tailscale", "app-b-tailscale"}


def test_reconcile_raises_on_terminal_proxy_error(ctx, service_krm_mock):
    # GIVEN a related app whose proxy has terminally failed
    with ready_ingress(("productpage", "apps")), proxy_states(
        productpage=proxy_state(error=True, message="ProxyFailed: bad config")
    ):
        # THEN reconcile raises (deferred to the end) so the unit goes to error
        with pytest.raises(Exception):
            ctx.run(
                ctx.on.config_changed(),
                make_state(ingress=1, config={"ready-timeout": 0}),
            )


def test_publish_urls_publishes_root_url_when_ready(ctx, service_krm_mock, ingress_io):
    # GIVEN a ready proxy
    with ready_ingress(("productpage", "apps", 8080)), proxy_states(
        productpage=proxy_state(hostname="productpage.ts.net")
    ):
        ctx.run(ctx.on.config_changed(), make_state(ingress=1))
    # THEN the root URL (no path prefix) is published
    ingress_io.publish_url.assert_called_once()
    _relation, url = ingress_io.publish_url.call_args.args
    assert url == "http://productpage.ts.net:8080/"


def test_publish_urls_wipes_stale_data_on_terminal_failure(
    ctx, service_krm_mock, ingress_io
):
    # GIVEN a terminally failed proxy, the reconcile raises (deferred) after wiping
    with ready_ingress(("productpage", "apps")), proxy_states(
        productpage=proxy_state(error=True, message="ProxyInvalid: nope")
    ):
        with pytest.raises(Exception):
            ctx.run(ctx.on.config_changed(), make_state(ingress=1))
    # THEN no URL is published and the stale URL is wiped
    ingress_io.publish_url.assert_not_called()
    ingress_io.wipe_ingress_data.assert_called_once()


def test_publish_urls_pending_does_not_error(ctx, service_krm_mock, ingress_io):
    # GIVEN a proxy that is merely slow (still pending past the timeout)
    with ready_ingress(("productpage", "apps")), proxy_states(
        productpage=proxy_state(pending=True, message="waiting for proxy")
    ):
        # THEN the reconcile completes without raising (stays Waiting via collect-status)
        ctx.run(ctx.on.config_changed(), make_state(ingress=1))
    ingress_io.publish_url.assert_not_called()


def test_proxy_state_hostname_ready(ctx, mock_lightkube_client):
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        mock_lightkube_client.get.return_value = _fake_service(
            hostname="productpage.ts.net"
        )
        state = mgr.charm._proxy_state("productpage", "apps")
    assert state == proxy_state(hostname="productpage.ts.net")


def test_proxy_state_pending_when_no_address(ctx, mock_lightkube_client):
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        mock_lightkube_client.get.return_value = _fake_service(
            condition=("ProxyPending", "no hostname yet")
        )
        state = mgr.charm._proxy_state("productpage", "apps")
    assert state.pending is True
    assert state.error is False
    assert state.message == "no hostname yet"


def test_proxy_state_error_on_terminal_condition(ctx, mock_lightkube_client):
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        mock_lightkube_client.get.return_value = _fake_service(
            condition=("ProxyFailed", "boom")
        )
        state = mgr.charm._proxy_state("productpage", "apps")
    assert state.error is True
    assert state.pending is False
    assert state.message == "boom"


def test_proxy_state_terminal_error_takes_precedence_over_stale_hostname(
    ctx, mock_lightkube_client
):
    # GIVEN a proxy that has a lingering LB hostname but the operator now reports
    # a terminal ProxyInvalid (e.g. an invalid config applied after provisioning)
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        mock_lightkube_client.get.return_value = _fake_service(
            hostname="productpage.ts.net", condition=("ProxyInvalid", "bad config")
        )
        state = mgr.charm._proxy_state("productpage", "apps")
    # THEN the terminal error wins over the stale address
    assert state.error is True
    assert state.hostname is None
    assert state.message == "bad config"


def test_proxy_state_pending_when_service_absent(ctx, mock_lightkube_client):
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        mock_lightkube_client.get.side_effect = _api_error(404)
        state = mgr.charm._proxy_state("productpage", "apps")
    assert state.pending is True
    assert state.hostname is None


def test_build_service_shape(ctx):
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        svc = mgr.charm._build_service("productpage", "apps", 8080)
    assert svc.metadata.name == "productpage-tailscale"
    assert svc.metadata.namespace == "apps"
    assert svc.metadata.annotations == {"tailscale.com/hostname": "apps-productpage"}
    assert svc.spec.type == "LoadBalancer"
    assert svc.spec.loadBalancerClass == "tailscale"
    assert svc.spec.selector == {"app.kubernetes.io/name": "productpage"}
    assert [p.port for p in svc.spec.ports] == [8080]


def test_remove_deletes_services_on_last_unit(ctx, service_krm_mock):
    ctx.run(ctx.on.remove(), make_state(planned_units=0))
    service_krm_mock.delete.assert_called_once()


def test_remove_keeps_services_when_units_remain(ctx, service_krm_mock):
    ctx.run(ctx.on.remove(), make_state(planned_units=1))
    service_krm_mock.delete.assert_not_called()


def test_unexpected_api_error_is_not_swallowed(ctx, mock_lightkube_client):
    # GIVEN the trust probe fails with a non-auth error (API unreachable, 500, ...)
    mock_lightkube_client.list.side_effect = _api_error(500)
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        # THEN the error surfaces rather than being misreported as "untrusted"
        with pytest.raises(ApiError):
            _ = mgr.charm._trusted
        mock_lightkube_client.list.side_effect = None
