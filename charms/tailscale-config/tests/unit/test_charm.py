# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

from unittest.mock import patch

import pytest
from ops import testing

from backend_tailscale import RootClientInfo, TailscaleAPIError
from charm import TailscaleConfigCharm
from tailscale_config import CharmState

ROOT_CREDENTIAL_URI = "secret:cvh7kruupa1s46bqvuig"


def test_active_status():
    """A valid backend with a root credential set reports active."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(
        config={"backend": "tailscale", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()


def test_blocked_without_root_credential():
    """Without a root credential the charm blocks."""
    # Arrange:
    ctx = testing.Context(TailscaleConfigCharm)
    state_in = testing.State(config={"backend": "tailscale"})

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
        config={"backend": "bogus", "root-credential": ROOT_CREDENTIAL_URI},
    )

    # Act:
    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert "bogus" in state_out.unit_status.message


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
