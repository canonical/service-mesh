# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

import json
from unittest.mock import MagicMock, patch

import pytest

from backend_tailscale import (
    IncompleteRootCredentialError,
    MintedClientInfo,
    MissingRootCredentialError,
    RootClientInfo,
    TailscaleAPIError,
    TailscaleBackend,
    UnreadableRootCredentialError,
    UnsupportedBackendError,
    get_root_client_info,
    mint_child_client,
    revoke_child_client,
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
    info = TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()

    # Assert:
    assert info == RootClientInfo(
        id="kABCDEFCNTRL",
        key_type="client",
        created="2026-01-01T00:00:00Z",
        scopes=["oauth_keys", "auth_keys"],
        user_id="uABCDEF",
    )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_parses_tags(mock_https):
    # Arrange:
    key_body = json.dumps({"id": "kABCDEFCNTRL", "tags": ["tag:k8s-operator", "tag:k8s"]})
    conn = _connection_for_flow(key=(200, key_body))
    mock_https.return_value = conn

    # Act:
    info = TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()

    # Assert:
    assert info.tags == ["tag:k8s-operator", "tag:k8s"]


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_exchanges_token_then_reads_key(mock_https):
    # Arrange:
    conn = _connection_for_flow()
    mock_https.return_value = conn

    # Act:
    TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()

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
def test_access_token_is_cached_across_calls(mock_https):
    # Arrange: one token, then two key GETs. Only one token exchange expected.
    conn = MagicMock()
    key_body = json.dumps({"id": "kABCDEFCNTRL"})
    conn.getresponse.side_effect = [
        _FakeResponse(200, _TOKEN_OK),
        _FakeResponse(200, key_body),
        _FakeResponse(200, key_body),
    ]
    mock_https.return_value = conn

    # Act: two operations on the same backend instance.
    backend = TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret")
    backend.get_root_client_info()
    backend.get_root_client_info()

    # Assert: exactly one token exchange, two key GETs.
    paths = [call.args[1] for call in conn.request.call_args_list]
    assert paths.count("/api/v2/oauth/token") == 1
    assert paths.count("/api/v2/tailnet/-/keys/kABCDEFCNTRL") == 2


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_token_http_error(mock_https):
    # Arrange:
    conn = _connection_returning(401, '{"message": "unauthorized"}')
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="HTTP 401"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_when_token_missing(mock_https):
    # Arrange:
    conn = _connection_returning(200, json.dumps({"token_type": "Bearer"}))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="access_token"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_http_error(mock_https):
    # Arrange: token exchange succeeds, keys GET fails.
    conn = _connection_for_flow(key=(403, '{"message": "forbidden"}'))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="HTTP 403"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_invalid_json(mock_https):
    # Arrange: token exchange succeeds, keys GET returns garbage.
    conn = _connection_for_flow(key=(200, "not json"))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="invalid JSON"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_non_object_json(mock_https):
    # Arrange: token exchange succeeds, keys GET returns a JSON array.
    conn = _connection_for_flow(key=(200, json.dumps(["not", "an", "object"])))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="expected a JSON object"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_request_raises_on_transport_error(mock_https):
    # Arrange:
    conn = MagicMock()
    conn.request.side_effect = OSError("connection refused")
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="failed to reach"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


_MINT_OK = json.dumps(
    {
        "id": "kCHILD",
        "key": "tskey-client-kCHILD",
        "keyType": "client",
        "created": "2026-07-21T12:14:58Z",
        "scopes": ["devices:core", "oauth_keys"],
        "tags": ["tag:k8s-operator"],
    }
)


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_mint_child_client_parses_response(mock_https):
    # Arrange: token exchange then mint POST.
    conn = _connection_for_flow(key=(200, _MINT_OK))
    mock_https.return_value = conn

    # Act:
    minted = TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").mint_child_client(
        tags=["tag:k8s-operator"],
        scopes=["oauth_keys", "devices:core"],
    )

    # Assert:
    assert minted == MintedClientInfo(
        id="kCHILD",
        key="tskey-client-kCHILD",
        key_type="client",
        created="2026-07-21T12:14:58Z",
        scopes=["devices:core", "oauth_keys"],
        tags=["tag:k8s-operator"],
    )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_mint_child_client_posts_preauthorized_body(mock_https):
    # Arrange:
    conn = _connection_for_flow(key=(200, _MINT_OK))
    mock_https.return_value = conn

    # Act:
    TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").mint_child_client(
        tags=["tag:k8s-operator"],
        scopes=["oauth_keys", "devices:core"],
    )

    # Assert: second call is the mint POST with the expected JSON body + headers.
    _token_call, mint_call = conn.request.call_args_list
    method, path = mint_call.args
    headers = mint_call.kwargs["headers"]
    body = json.loads(mint_call.kwargs["body"])
    assert method == "POST"
    assert path == "/api/v2/tailnet/-/keys"
    assert headers["Authorization"] == "Bearer tskey-token-abc"
    assert headers["Content-Type"] == "application/json"
    assert body["keyType"] == "client"
    assert body["preauthorized"] is True
    assert body["tags"] == ["tag:k8s-operator"]
    assert body["scopes"] == ["oauth_keys", "devices:core"]
    assert body["description"]


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_mint_child_client_raises_on_http_error(mock_https):
    # Arrange: token exchange succeeds, mint POST fails.
    conn = _connection_for_flow(key=(403, '{"message": "actor cannot set scopes"}'))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="HTTP 403"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").mint_child_client(
            tags=[], scopes=["oauth_keys"]
        )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_mint_child_client_raises_when_key_missing(mock_https):
    # Arrange: mint response omits the secret key.
    conn = _connection_for_flow(key=(200, json.dumps({"id": "kCHILD"})))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="key secret"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").mint_child_client(
            tags=[], scopes=["oauth_keys"]
        )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_mint_child_client_raises_when_key_id_missing(mock_https):
    # Arrange: mint response omits the key id.
    conn = _connection_for_flow(key=(200, json.dumps({"key": "tskey-client-kCHILD"})))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="key id"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").mint_child_client(
            tags=[], scopes=["oauth_keys"]
        )


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_get_root_client_info_raises_on_empty_body(mock_https):
    # Arrange: token exchange succeeds, keys GET returns an empty body.
    conn = _connection_for_flow(key=(200, ""))
    mock_https.return_value = conn

    # Act / Assert: _request returns None -> _request_object rejects it.
    with pytest.raises(TailscaleAPIError, match="expected a JSON object"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").get_root_client_info()


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_revoke_child_client_deletes_key(mock_https):
    # Arrange: token exchange then DELETE returning null.
    conn = _connection_for_flow(key=(200, "null"))
    mock_https.return_value = conn

    # Act:
    TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").revoke_child_client(key_id="kCHILD")

    # Assert: second call is the DELETE with a Bearer header.
    _token_call, delete_call = conn.request.call_args_list
    method, path = delete_call.args
    headers = delete_call.kwargs["headers"]
    assert method == "DELETE"
    assert path == "/api/v2/tailnet/-/keys/kCHILD"
    assert headers["Authorization"] == "Bearer tskey-token-abc"


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_revoke_child_client_raises_on_http_error(mock_https):
    # Arrange: token exchange succeeds, DELETE fails.
    conn = _connection_for_flow(key=(404, '{"message": "not found"}'))
    mock_https.return_value = conn

    # Act / Assert:
    with pytest.raises(TailscaleAPIError, match="HTTP 404"):
        TailscaleBackend("kABCDEFCNTRL", "tskey-client-secret").revoke_child_client(
            key_id="kCHILD"
        )


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


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_helper_mint_child_client_inherits_parent_tags(mock_https):
    # Arrange: one token exchange, then the parent GET-key and the mint POST
    # reuse the cached token.
    parent_key = json.dumps({"id": "kABCDEFCNTRL", "tags": ["tag:k8s-operator", "tag:k8s"]})
    conn = MagicMock()
    conn.getresponse.side_effect = [
        _FakeResponse(200, _TOKEN_OK),
        _FakeResponse(200, parent_key),
        _FakeResponse(200, _MINT_OK),
    ]
    mock_https.return_value = conn

    # Act:
    minted = mint_child_client(_tailscale_state(), scopes=["oauth_keys", "devices:core"])

    # Assert: the mint POST carries the parent's tags, after a single token
    # exchange shared by the GET-key and the POST.
    assert minted.id == "kCHILD"
    assert minted.key == "tskey-client-kCHILD"
    paths = [call.args[1] for call in conn.request.call_args_list]
    assert paths == [
        "/api/v2/oauth/token",
        "/api/v2/tailnet/-/keys/kABCDEFCNTRL",
        "/api/v2/tailnet/-/keys",
    ]
    mint_call = conn.request.call_args_list[2]
    body = json.loads(mint_call.kwargs["body"])
    assert body["tags"] == ["tag:k8s-operator", "tag:k8s"]
    assert body["scopes"] == ["oauth_keys", "devices:core"]


@pytest.mark.parametrize(
    "state, expected",
    [
        (_tailscale_state(backend="headscale"), UnsupportedBackendError),
        (_tailscale_state(content=None, root_credential=None), MissingRootCredentialError),
        (_tailscale_state(content=None), UnreadableRootCredentialError),
        (_tailscale_state({"client-id": "kABCDEFCNTRL"}), IncompleteRootCredentialError),
    ],
)
def test_helper_mint_child_client_validates_state(state, expected):
    # Act / Assert:
    with pytest.raises(expected):
        mint_child_client(state, scopes=["oauth_keys"])


@patch("backend_tailscale.http.client.HTTPSConnection")
def test_helper_revoke_child_client(mock_https):
    # Arrange: token exchange then DELETE.
    conn = _connection_for_flow(key=(200, "null"))
    mock_https.return_value = conn

    # Act:
    revoke_child_client(_tailscale_state(), key_id="kCHILD")

    # Assert:
    method, path = conn.request.call_args_list[1].args
    assert method == "DELETE"
    assert path == "/api/v2/tailnet/-/keys/kCHILD"


@pytest.mark.parametrize(
    "state, expected",
    [
        (_tailscale_state(backend="headscale"), UnsupportedBackendError),
        (_tailscale_state(content=None, root_credential=None), MissingRootCredentialError),
        (_tailscale_state(content=None), UnreadableRootCredentialError),
        (_tailscale_state({"client-id": "kABCDEFCNTRL"}), IncompleteRootCredentialError),
    ],
)
def test_helper_revoke_child_client_validates_state(state, expected):
    # Act / Assert:
    with pytest.raises(expected):
        revoke_child_client(state, key_id="kCHILD")
