# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import scenario

from credentials import resolve_credentials


def test_manual_credentials(ctx, manual_secret):
    state = scenario.State(
        config={
            "credentials": manual_secret.id,
            "login-server": "https://headscale.example.com",
            "advertise-tags": "tag:server, tag:juju",
        },
        secrets=[manual_secret],
        relations=[scenario.SubordinateRelation("juju-info")],
    )
    with ctx(ctx.on.collect_unit_status(), state) as manager:
        credentials, error = resolve_credentials(manager.charm)
    assert error is None
    assert credentials is not None
    assert credentials.auth_key == "tskey-auth-test"
    assert credentials.login_server == "https://headscale.example.com"
    assert credentials.tags == ("tag:server", "tag:juju")
    assert credentials.ephemeral is True


def test_relation_credentials(ctx):
    secret = scenario.Secret(
        tracked_content={"auth-key": "tskey-client-test", "client-id": "client-id"}
    )
    relation = scenario.Relation(
        "tailscale-credentials",
        remote_app_name="tailscale-config",
        remote_app_data={
            "secret_id": secret.id,
            "login_server": "https://controlplane.tailscale.com",
            "tags": "tag:server,tag:juju",
        },
    )
    state = scenario.State(
        config={"ephemeral": False},
        secrets=[secret],
        relations=[scenario.SubordinateRelation("juju-info"), relation],
    )
    with ctx(ctx.on.relation_changed(relation), state) as manager:
        credentials, error = resolve_credentials(manager.charm)
    assert error is None
    assert credentials is not None
    assert credentials.auth_key == "tskey-client-test"
    assert credentials.tags == ("tag:server", "tag:juju")
    assert credentials.ephemeral is False


def test_both_sources_conflict(ctx, manual_secret):
    relation = scenario.Relation("tailscale-credentials")
    state = scenario.State(
        config={"credentials": manual_secret.id},
        secrets=[manual_secret],
        relations=[scenario.SubordinateRelation("juju-info"), relation],
    )
    with ctx(ctx.on.collect_unit_status(), state) as manager:
        credentials, error = resolve_credentials(manager.charm)
    assert credentials is None
    assert error is not None
    assert error.startswith("Both")


def test_missing_auth_key(ctx):
    secret = scenario.Secret(
        tracked_content={"unrelated": "value"},
        latest_content={"unrelated": "value"},
        owner="app",
    )
    state = scenario.State(
        config={"credentials": secret.id},
        secrets=[secret],
        relations=[scenario.SubordinateRelation("juju-info")],
    )
    with ctx(ctx.on.collect_unit_status(), state) as manager:
        credentials, error = resolve_credentials(manager.charm)
    assert credentials is None
    assert error == "Credentials secret is missing required field: auth-key"
