# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import ops
import pytest
from conftest import make_state

import extensions

MQTTS = {
    "name": "mqtts",
    "protocol": "tls-terminate",
    "port": 8883,
    "service": "emqx",
    "namespace": "core",
    "service_port": 1883,
}
QUIC = {
    "name": "mqtt-quic",
    "protocol": "udp",
    "port": 14567,
    "service": "emqx",
    "namespace": "core",
    "service_port": 14567,
}


def _run(ctx, config, **kw):
    with ctx(ctx.on.config_changed(), make_state(config=config, **kw)) as mgr:
        mgr.run()
        return mgr.charm


def test_parse_cidrs_normalises_bare_ips():
    assert extensions.parse_cidrs("1.2.3.4, 10.0.0.0/8 ::1") == [
        "1.2.3.4/32",
        "10.0.0.0/8",
        "::1/128",
    ]


@pytest.mark.parametrize("bad", ["nope", "1.2.3.4/99"])
def test_parse_cidrs_rejects_garbage(bad):
    with pytest.raises(extensions.ConfigError):
        extensions.parse_cidrs(bad)


def test_parse_extra_routes_rejects_port_clash_and_reserved():
    clash = json.dumps([MQTTS, {**MQTTS, "name": "other", "protocol": "tcp"}])
    with pytest.raises(extensions.ConfigError, match="reuses"):
        extensions.parse_extra_routes(clash)
    with pytest.raises(extensions.ConfigError, match="reserved"):
        extensions.parse_extra_routes(json.dumps([{**MQTTS, "port": 443}]))


def test_tcp_and_udp_may_share_a_port_number():
    routes = extensions.parse_extra_routes(
        json.dumps([{**MQTTS, "protocol": "tcp"}, {**QUIC, "port": 8883}])
    )
    assert len(routes) == 2


def test_tls_terminate_listener_requires_secret():
    routes = extensions.parse_extra_routes(json.dumps([MQTTS]))
    assert extensions.l4_listeners(routes, None) == []
    (listener,) = extensions.l4_listeners(routes, {"name": "s"})
    assert listener["protocol"] == "TLS" and listener["tls"]["mode"] == "Terminate"


def test_gateway_gets_l4_listeners_addresses(ctx, gateway_class_accepted, krm_mocks, certs_ready):
    cfg = {"extra-routes": json.dumps([MQTTS, QUIC]), "external-ips": "10.16.0.5"}
    _run(ctx, cfg, certificates=True)
    (gateway,) = krm_mocks.gateway.reconcile.call_args.args[0]
    names = {x["name"]: x for x in gateway.spec["listeners"]}
    assert names["tls-terminate-8883"]["tls"]["mode"] == "Terminate"
    assert names["udp-14567"]["protocol"] == "UDP"
    assert gateway.spec["addresses"] == [{"type": "IPAddress", "value": "10.16.0.5"}]
    routes = krm_mocks.l4_route.reconcile.call_args.args[0]
    assert {type(r) for r in routes} == {extensions.TCPRoute, extensions.UDPRoute}


def test_tls_terminate_route_withheld_until_cert(
    ctx, gateway_class_accepted, krm_mocks, certs_absent
):
    _run(ctx, {"extra-routes": json.dumps([MQTTS])})
    assert krm_mocks.l4_route.reconcile.call_args.args[0] == []


def test_allowlist_creates_authorization_policy(ctx, gateway_class_accepted, krm_mocks):
    _run(ctx, {"allowed-cidrs": "1.2.3.4,10.0.0.0/8"})
    (policy,) = krm_mocks.security_policy.reconcile.call_args.args[0]
    authz = policy.spec["authorization"]
    assert authz["defaultAction"] == "Deny"
    assert authz["rules"][0]["principal"]["clientCIDRs"] == ["1.2.3.4/32", "10.0.0.0/8"]
    krm_mocks.ext_auth_backend.delete.assert_called()


def test_no_allowlist_no_policy(ctx, gateway_class_accepted, krm_mocks):
    _run(ctx, {})
    krm_mocks.security_policy.delete.assert_called()
    krm_mocks.security_policy.reconcile.assert_not_called()


def test_http3_policy_needs_tls(ctx, gateway_class_accepted, krm_mocks, certs_absent):
    _run(ctx, {"http3": True})
    krm_mocks.http3_policy.reconcile.assert_not_called()


def test_http3_policy_applied_with_tls(ctx, gateway_class_accepted, krm_mocks, certs_ready):
    _run(ctx, {"http3": True}, certificates=True)
    (policy,) = krm_mocks.http3_policy.reconcile.call_args.args[0]
    assert policy.spec["http3"] == {}


def test_extra_http_route_has_hostnames_and_redirect(
    ctx, gateway_class_accepted, krm_mocks, certs_ready
):
    route = {
        "name": "ui",
        "service": "ui",
        "namespace": "core",
        "service_port": 80,
        "hostnames": ["telemetry.example.com"],
    }
    _run(ctx, {"extra-routes": json.dumps([route])}, certificates=True)
    routes = {r.metadata.name: r for r in krm_mocks.httproute.reconcile.call_args.args[0]}
    assert routes["ui"].spec["hostnames"] == ["telemetry.example.com"]
    assert routes["ui-redirect"].spec["rules"][0]["filters"][0]["type"] == "RequestRedirect"


def test_invalid_extension_config_blocks_and_applies_nothing(
    ctx, gateway_class_accepted, krm_mocks
):
    with ctx(ctx.on.config_changed(), make_state(config={"allowed-cidrs": "bogus"})) as mgr:
        state = mgr.run()
    assert isinstance(state.unit_status, ops.BlockedStatus)
    krm_mocks.gateway.reconcile.assert_not_called()


def test_non_leader_never_writes_to_the_cluster(ctx, gateway_class_accepted, krm_mocks):
    _run(ctx, {"allowed-cidrs": "1.2.3.4"}, leader=False)
    krm_mocks.gateway.reconcile.assert_not_called()
    krm_mocks.security_policy.reconcile.assert_not_called()


def test_additional_hostnames_added_to_cert_sans_and_open_listener(
    ctx, gateway_class_accepted, krm_mocks
):
    cfg = {"external_hostname": "a.example.com", "additional-hostnames": "b.example.com"}
    charm = _run(ctx, cfg)
    assert set(charm._certificate_request.sans_dns) == {"a.example.com", "b.example.com"}
    (gateway,) = krm_mocks.gateway.reconcile.call_args.args[0]
    assert "hostname" not in gateway.spec["listeners"][0]


def test_byo_tls_secret_serves_https_without_relation(
    ctx, gateway_class_accepted, krm_mocks, certs_absent
):
    _run(ctx, {"tls-secret-name": "my-cert"})
    (gateway,) = krm_mocks.gateway.reconcile.call_args.args[0]
    https = [x for x in gateway.spec["listeners"] if x["name"] == "https"][0]
    assert https["tls"]["certificateRefs"][0]["name"] == "my-cert"
    krm_mocks.tls_secret.reconcile.assert_not_called()
    krm_mocks.tls_secret.delete.assert_not_called()
