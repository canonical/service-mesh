# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

import json
from unittest.mock import MagicMock, patch

import pytest

from backend_tailscale import (
    IncompleteRootCredentialError,
    MissingRootCredentialError,
    RootClientInfo,
    TailscaleAPIError,
    TailscaleBackend,
    UnreadableRootCredentialError,
    UnsupportedBackendError,
    get_root_client_info,
)
from tailscale_config import CharmState


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")


_TOKEN_OK = json.dumps({"access_token": "tskey-token-abc", "token_type": "Bearer"})


def _connection_returning(status: int, body: str) -> MagicMock:
    conn = MagicMock()
    conn.getresponse.return_value = _FakeResponse(status, body)
    return conn


def _connection_for_flow(
    *,
    token: tuple[int, str] = (200, _TOKEN_OK),
    key: tuple[int, str] = (200, json.dumps({"id": "kABCDEFCNTRL"})),
) -> MagicMock:
    """Return a connection whose two sequential requests are the token POST then the keys GET."""
    conn = MagicMock()
    conn.getresponse.side_effect = [
        _FakeResponse(*token),
        _FakeResponse(*key),
    ]
    return conn


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_parses_response(mock_https):
    # Arrange:
    key_body = json.dumps(
        {
            "id": "kABCDEFCNTRL",
            "keyType": "client",
            "created": "2026-01-01T00:00:00Z",
            "scopes": ["oauth_keys", "auth_keys"],
            "userId": "uABCDEF",
        }
    )
    conn = _connection_for_flow(key=(200, key_body))
    mock_https.return_value = conn

    # Act:
    info = TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")

    # Assert:
    assert info == RootClientInfo(
        id="kABCDEFCNTRL",
        key_type="client",
        created="2026-01-01T00:00:00Z",
        scopes=["oauth_keys", "auth_keys"],
        user_id="uABCDEF",
    )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_exchanges_token_then_reads_key(mock_https):
    # Arrange:
    conn = _connection_for_flow()
    mock_https.return_value = conn

    # Act:
    TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")

    # Assert: first call is the token exchange POST.
    token_call, key_call = conn.request.call_args_list
    token_method, token_path = token_call.args
    token_body = token_call.kwargs["body"]
    assert token_method == "POST"
    assert token_path == "/api/v2/oauth/token"
    assert "grant_type=client_credentials" in token_body
    assert "client_id=kABCDEFCNTRL" in token_body
    assert "client_secret=tskey-client-secret" in token_body

    # Assert: second call reads the key with the *exchanged* access token.
    key_method, key_path = key_call.args
    key_headers = key_call.kwargs["headers"]
    assert key_method == "GET"
    assert key_path == "/api/v2/tailnet/-/keys/kABCDEFCNTRL"
    assert key_headers["Authorization"] == "Bearer tskey-token-abc"


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_token_http_error(mock_https):
    # Arrange:
    conn = _connection_returning(401, '{"message": "unauthorized"}')
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="HTTP 401"):
        TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_when_token_missing(mock_https):
    # Arrange:
    conn = _connection_returning(200, json.dumps({"token_type": "Bearer"}))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="access_token"):
        TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_http_error(mock_https):
    # Arrange: token exchange succeeds, keys GET fails.
    conn = _connection_for_flow(key=(403, '{"message": "forbidden"}'))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="HTTP 403"):
        TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_invalid_json(mock_https):
    # Arrange: token exchange succeeds, keys GET returns garbage.
    conn = _connection_for_flow(key=(200, "not json"))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="invalid JSON"):
        TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_non_object_json(mock_https):
    # Arrange: token exchange succeeds, keys GET returns a JSON array.
    conn = _connection_for_flow(key=(200, json.dumps(["not", "an", "object"])))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="expected a JSON object"):
        TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_request_raises_on_transport_error(mock_https):
    # Arrange:
    conn = MagicMock()
    conn.request.side_effect = OSError("connection refused")
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="failed to reach"):
        TailscaleBackend().get_root_client_info("kABCDEFCNTRL", "tskey-client-secret")


_FULL_CREDENTIAL = {"client-id": "kABCDEFCNTRL", "client-secret": "tskey-client-secret"}


def _tailscale_state(
    content: dict[str, str] | None = _FULL_CREDENTIAL,
    *,
    backend: str = "tailscale",
    root_credential: str | None = "secret:x",
) -> CharmState:
    return CharmState(
        backend=backend,
        root_credential=root_credential,
        root_credential_content=content,
        login_server=None,
    )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_helper_get_root_client_info(mock_https):
    # Arrange:
    conn = _connection_for_flow()
    mock_https.return_value = conn

    # Act:
    info = get_root_client_info(_tailscale_state())

    # Assert:
    assert info.id == "kABCDEFCNTRL"
    _, key_path = conn.request.call_args_list[1].args
    assert key_path == "/api/v2/tailnet/-/keys/kABCDEFCNTRL"


def test_helper_rejects_non_tailscale_backend():
    # Act / Assert:
    with pytest.raises(UnsupportedBackendError, match="tailscale"):
        get_root_client_info(_tailscale_state(backend="headscale"))


def test_helper_rejects_missing_root_credential():
    # Act / Assert:
    with pytest.raises(MissingRootCredentialError, match="root-credential config"):
        get_root_client_info(_tailscale_state(content=None, root_credential=None))


def test_helper_rejects_unreadable_root_credential():
    # Act / Assert:
    with pytest.raises(UnreadableRootCredentialError, match="not found"):
        get_root_client_info(_tailscale_state(content=None))


def test_helper_rejects_incomplete_credential():
    # Act / Assert:
    with pytest.raises(IncompleteRootCredentialError, match="client-secret"):
        get_root_client_info(_tailscale_state({"client-id": "kABCDEFCNTRL"}))
