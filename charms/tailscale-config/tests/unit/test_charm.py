# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import json
from unittest.mock import patch

import pytest
from ops import testing
from scenario.errors import UncaughtCharmError

from backend_tailscale import MintedClientInfo, RootClientInfo, TailscaleAPIError
from charm import CREDENTIAL_MAP_KEY, PEER_RELATION_NAME, TailscaleConfigCharm
from tailscale_config import TAILSCALE_LOGIN_SERVER, CharmState

ROOT_CREDENTIAL_URI = "secret:cvh7kruupa1s46bqvuig"


def test_active_status():
    """A leader with a root credential and peer relation reports active."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        relations={testing.PeerRelation(PEER_RELATION_NAME)},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()


def test_non_leader_reports_standby():
    """A non-leader unit reports active standby and does no work."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(leader=False)

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.ActiveStatus)
    assert "standby" in state_out.unit_status.message


def test_maintenance_without_peer_relation():
    """Without the peer relation the leader reports maintenance."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.MaintenanceStatus)
    assert "peer relation" in state_out.unit_status.message


def test_blocked_without_root_credential():
    """Without a root credential the charm blocks."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(leader=True, config={"backend": "tailscale"})

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "root-credential" in state_out.unit_status.message


def test_blocked_on_invalid_backend():
    """An unrecognized backend blocks, even with a root credential set."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        leader=True,
        config={"backend": "bogus", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "bogus" in state_out.unit_status.message


def test_blocked_on_headscale_without_login_server():
    """The headscale backend blocks when no login-server is configured."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        leader=True,
        config={"backend": "headscale", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "login-server" in state_out.unit_status.message


def test_collect_state_normalizes_empty_login_server():
    """An empty login-server config collapses to None."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={
            "backend": "headscale",
            "login-server": "",
            "root-credential": ROOT_CREDENTIAL_URI,
        },
    )

    # Act:
    with ctx(ctx.on.collect_unit_status(), state_in) as manager:
        state = manager.charm._collect_state()

    # Assert:
    assert state == CharmState(
        backend="headscale",
        root_credential=ROOT_CREDENTIAL_URI,
        login_server=None,
    )


def _tailscale_secret(**content):
    return testing.Secret(
        {"client-id": "kABCDEFCNTRL", "client-secret": "tskey-client-secret", **content},
        id=ROOT_CREDENTIAL_URI,
    )


def test_get_root_client_info_reports_client_details():
    """The action returns the fields fetched from the Tailscale API."""
    # Arrange:
    secret = _tailscale_secret()
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={secret},
    )
    info = RootClientInfo(
        id="kABCDEFCNTRL",
        key_type="client",
        created="2026-01-01T00:00:00Z",
        scopes=["oauth_keys", "auth_keys"],
        user_id="uABCDEF",
    )

    # Act:
    with patch("charm.get_root_client_info", return_value=info) as mock_get:
        ctx.run(ctx.on.action("get-root-client-info"), state_in)

    # Assert:
    assert mock_get.call_count == 1
    assert ctx.action_results == {
        "id": "kABCDEFCNTRL",
        "key-type": "client",
        "created": "2026-01-01T00:00:00Z",
        "scopes": "oauth_keys, auth_keys",
        "user-id": "uABCDEF",
    }


def test_get_root_client_info_fails_on_non_tailscale_backend():
    """The action fails when the backend is not tailscale."""
    # Arrange:
    secret = _tailscale_secret()
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "headscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={secret},
    )

    # Act / Assert:
    with pytest.raises(testing.ActionFailed) as exc:
        ctx.run(ctx.on.action("get-root-client-info"), state_in)
    assert "tailscale" in exc.value.message


def test_get_root_client_info_fails_without_root_credential():
    """The action fails when no root credential is configured."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(config={"backend": "tailscale"})

    # Act / Assert:
    with pytest.raises(testing.ActionFailed) as exc:
        ctx.run(ctx.on.action("get-root-client-info"), state_in)
    assert "root-credential" in exc.value.message


def test_get_root_client_info_fails_on_incomplete_secret():
    """The action fails when the secret lacks client-id/client-secret."""
    # Arrange:
    secret = testing.Secret({"client-id": "kABCDEFCNTRL"}, id=ROOT_CREDENTIAL_URI)
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={secret},
    )

    # Act / Assert:
    with pytest.raises(testing.ActionFailed) as exc:
        ctx.run(ctx.on.action("get-root-client-info"), state_in)
    assert "client-secret" in exc.value.message


def test_get_root_client_info_fails_on_api_error():
    """A Tailscale API error surfaces as an action failure."""
    # Arrange:
    secret = _tailscale_secret()
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={secret},
    )

    # Act / Assert:
    with patch(
        "charm.get_root_client_info",
        side_effect=TailscaleAPIError("boom"),
    ):
        with pytest.raises(testing.ActionFailed) as exc:
            ctx.run(ctx.on.action("get-root-client-info"), state_in)
    assert "boom" in exc.value.message


def _minted(**overrides):
    return MintedClientInfo(
        id=overrides.get("id", "kCHILD001"),
        key=overrides.get("key", "tskey-client-CHILD001"),
        key_type="client",
        created="2026-01-01T00:00:00Z",
        scopes=["auth_keys", "devices:core"],
        tags=overrides.get("tags", ["tag:k8s-operator"]),
    )


def _credential_map(relations) -> dict:
    """Return the provider's ``relation-id -> key_id`` map from the peer databag."""
    peer = next(r for r in relations if r.endpoint == PEER_RELATION_NAME)
    raw = peer.local_app_data.get(CREDENTIAL_MAP_KEY)
    return json.loads(raw) if raw else {}


def test_new_relation_mints_and_publishes():
    """A new relation mints a child, grants a secret, and publishes app data."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    peer = testing.PeerRelation(PEER_RELATION_NAME)
    downstream = testing.Relation("tailscale-credentials")
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={_tailscale_secret()},
        relations={peer, downstream},
    )

    # Act:
    with patch("charm.mint_child_client", return_value=_minted()) as mock_mint:
        state_out = ctx.run(ctx.on.relation_created(downstream), state_in)

    # Assert:
    assert mock_mint.call_count == 1
    assert _credential_map(state_out.relations) == {str(downstream.id): "kCHILD001"}
    published = state_out.get_relation(downstream.id).local_app_data
    assert published["secret_id"].startswith("secret:")
    assert published["login_server"] == TAILSCALE_LOGIN_SERVER
    assert published["tags"] == "tag:k8s-operator"


def test_peer_relation_created_resumes_mint():
    """A peer-relation-created event runs reconcile for a pending relation.

    Exercises the resume path: work skipped while the peer relation was absent
    is picked up once it becomes available.
    """
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    peer = testing.PeerRelation(PEER_RELATION_NAME)
    downstream = testing.Relation("tailscale-credentials")
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={_tailscale_secret()},
        relations={peer, downstream},
    )

    # Act:
    with patch("charm.mint_child_client", return_value=_minted()) as mock_mint:
        state_out = ctx.run(ctx.on.relation_created(peer), state_in)

    # Assert:
    assert mock_mint.call_count == 1
    assert _credential_map(state_out.relations) == {str(downstream.id): "kCHILD001"}


def test_existing_relation_is_not_reminted():
    """A relation already in the peer map is not minted again."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    downstream = testing.Relation("tailscale-credentials")
    peer = testing.PeerRelation(
        PEER_RELATION_NAME,
        local_app_data={CREDENTIAL_MAP_KEY: json.dumps({str(downstream.id): "kCHILD001"})},
    )
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={_tailscale_secret()},
        relations={peer, downstream},
    )

    # Act:
    with patch("charm.mint_child_client", return_value=_minted()) as mock_mint:
        state_out = ctx.run(ctx.on.relation_changed(downstream), state_in)

    # Assert:
    assert mock_mint.call_count == 0
    assert _credential_map(state_out.relations) == {str(downstream.id): "kCHILD001"}


def test_departed_relation_revokes_child():
    """A key_id whose relation is gone is revoked and dropped from the map."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    peer = testing.PeerRelation(
        PEER_RELATION_NAME,
        local_app_data={CREDENTIAL_MAP_KEY: json.dumps({"999": "kCHILD999"})},
    )
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={_tailscale_secret()},
        relations={peer},
    )

    # Act:
    with patch("charm.revoke_child_client") as mock_revoke:
        state_out = ctx.run(ctx.on.update_status(), state_in)

    # Assert:
    assert mock_revoke.call_count == 1
    assert mock_revoke.call_args.kwargs["key_id"] == "kCHILD999"
    assert _credential_map(state_out.relations) == {}


def test_revoke_api_error_raises():
    """A revoke failure propagates so Juju retries the hook."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    peer = testing.PeerRelation(
        PEER_RELATION_NAME,
        local_app_data={CREDENTIAL_MAP_KEY: json.dumps({"999": "kCHILD999"})},
    )
    state_in = testing.State(
        leader=True,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={_tailscale_secret()},
        relations={peer},
    )

    # Act / Assert:
    with patch("charm.revoke_child_client", side_effect=TailscaleAPIError("boom")):
        with pytest.raises(UncaughtCharmError):
            ctx.run(ctx.on.update_status(), state_in)


def test_non_leader_does_not_mint():
    """A non-leader unit performs no mint/revoke and writes no map."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    peer = testing.PeerRelation(PEER_RELATION_NAME)
    downstream = testing.Relation("tailscale-credentials")
    state_in = testing.State(
        leader=False,
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
        secrets={_tailscale_secret()},
        relations={peer, downstream},
    )

    # Act:
    with patch("charm.mint_child_client", return_value=_minted()) as mock_mint:
        state_out = ctx.run(ctx.on.relation_created(downstream), state_in)

    # Assert:
    assert mock_mint.call_count == 0
    assert _credential_map(state_out.relations) == {}


def test_headscale_passes_configured_login_server():
    """The headscale backend publishes the configured login-server as-is."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    peer = testing.PeerRelation(PEER_RELATION_NAME)
    downstream = testing.Relation("tailscale-credentials")
    state_in = testing.State(
        leader=True,
        config={
            "backend": "headscale",
            "login-server": "https://headscale.example.com",
            "root-credential": ROOT_CREDENTIAL_URI,
        },
        secrets={_tailscale_secret()},
        relations={peer, downstream},
    )

    # Act:
    with patch("charm.mint_child_client", return_value=_minted()):
        state_out = ctx.run(ctx.on.relation_created(downstream), state_in)

    # Assert:
    published = state_out.get_relation(downstream.id).local_app_data
    assert published["login_server"] == "https://headscale.example.com"
