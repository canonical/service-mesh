# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Tailscale control-plane (OAuth) API interactions.

This module is deliberately free of charming concerns so it can be used
outside the context of a charm. It talks to the Tailscale SaaS API using only
the standard library (``http.client``), so it adds no runtime dependencies.
"""

import http.client
import json
import logging
import urllib.parse

from pydantic import BaseModel

from tailscale_config import BACKEND_TAILSCALE, CharmState

logger = logging.getLogger(__name__)

TAILSCALE_API_HOST = "api.tailscale.com"
"""Default host of the Tailscale SaaS API."""

_KEY_PATH = "/api/v2/tailnet/-/keys/{key_id}"
_KEYS_PATH = "/api/v2/tailnet/-/keys"
_TOKEN_PATH = "/api/v2/oauth/token"

DEFAULT_CHILD_DESCRIPTION = "Minted by the tailscale-config charm"
"""Default description stamped onto minted child OAuth clients."""

DEFAULT_CHILD_SCOPES = ["auth_keys", "devices:core"]
"""Fixed, provider-owned scopes requested for minted child OAuth clients."""


class RootClientError(Exception):
    """Base class for failures fetching root OAuth client info.

    The string representation is a user-facing message suitable for surfacing
    directly (e.g. via ``ops.ActionEvent.fail``).
    """


class MissingRootCredentialError(RootClientError):
    """Raised when no root-credential secret URI is configured."""

    def __init__(self) -> None:
        super().__init__("root-credential config is required")


class UnreadableRootCredentialError(RootClientError):
    """Raised when the root-credential secret cannot be read."""

    def __init__(self) -> None:
        super().__init__("root-credential secret not found; grant it to this application")


class UnsupportedBackendError(RootClientError):
    """Raised when the configured backend is not the Tailscale backend."""

    def __init__(self, backend: str) -> None:
        super().__init__(
            f"action only supported for the {BACKEND_TAILSCALE!r} backend, not {backend!r}"
        )


class IncompleteRootCredentialError(RootClientError):
    """Raised when the root-credential secret lacks the required fields."""

    def __init__(self) -> None:
        super().__init__("root-credential secret must contain 'client-id' and 'client-secret'")


class TailscaleAPIError(RootClientError):
    """Raised when the Tailscale API returns an error or an unexpected reply."""


class RootClientInfo(BaseModel):
    """Information about the root OAuth client, as reported by the API."""

    id: str
    """The OAuth client's key ID."""

    key_type: str | None
    """The kind of key, e.g. ``client``."""

    created: str | None
    """RFC 3339 creation timestamp, if reported."""

    scopes: list[str]
    """Scopes granted to the OAuth client."""

    user_id: str | None
    """ID of the user that owns the OAuth client, if reported."""

    tags: list[str] = []
    """Tags carried by the OAuth client, as reported by the API."""


class MintedClientInfo(BaseModel):
    """A freshly minted child OAuth client, as returned by the mint endpoint."""

    id: str
    """The child OAuth client's key ID."""

    key: str
    """The child client's secret (``tskey-client-...``); the credential to distribute."""

    key_type: str | None
    """The kind of key, e.g. ``client``."""

    created: str | None
    """RFC 3339 creation timestamp, if reported."""

    scopes: list[str]
    """Scopes granted to the child OAuth client."""

    tags: list[str]
    """Tags carried by the child OAuth client."""


class TailscaleBackend:
    """A thin client for the subset of the Tailscale API this charm needs."""

    def __init__(self, client_id: str, client_secret: str, *, host: str = TAILSCALE_API_HOST):
        self._client_id = client_id
        self._client_secret = client_secret
        self._host = host
        self._token: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: str | None = None,
    ) -> dict | None:
        """Perform an HTTPS request and return the decoded JSON body.

        Returns the decoded JSON object, or ``None`` when the body is empty or
        the JSON literal ``null``. Raises ``TailscaleAPIError`` on transport
        errors, non-2xx responses, or bodies that are neither a JSON object nor
        ``null``.
        """
        conn = http.client.HTTPSConnection(self._host)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            payload = response.read().decode("utf-8")
            status = response.status
        except OSError as exc:
            raise TailscaleAPIError(f"failed to reach {self._host}: {exc}") from exc
        finally:
            conn.close()

        if not 200 <= status < 300:
            raise TailscaleAPIError(f"{method} {path} returned HTTP {status}: {payload.strip()}")
        if not payload.strip():
            return None
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TailscaleAPIError(f"invalid JSON in response to {method} {path}") from exc
        if decoded is None:
            return None
        if not isinstance(decoded, dict):
            raise TailscaleAPIError(f"expected a JSON object in response to {method} {path}")
        return decoded

    def _request_object(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: str | None = None,
    ) -> dict:
        """Like ``_request`` but require a JSON object body.

        Raises ``TailscaleAPIError`` if the response body is empty or ``null``.
        """
        decoded = self._request(method, path, headers=headers, body=body)
        if decoded is None:
            raise TailscaleAPIError(f"expected a JSON object in response to {method} {path}")
        return decoded

    def _get_access_token(self) -> str:
        """Return a short-lived access token, reusing a cached one if present.

        Performs the OAuth2 ``client_credentials`` grant against the Tailscale
        token endpoint on the first call and caches the result. The token is
        short-lived but comfortably outlives a single charm hook, so no expiry
        tracking is needed. Raises ``TailscaleAPIError`` if the exchange fails
        or no token is returned.
        """
        if self._token is not None:
            return self._token

        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        )
        decoded = self._request_object(
            "POST",
            _TOKEN_PATH,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        access_token = decoded.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise TailscaleAPIError("token endpoint response did not contain an access_token")

        self._token = access_token
        return access_token

    def get_root_client_info(self) -> RootClientInfo:
        """Return information about the root OAuth client.

        First exchanges the OAuth client credentials for a short-lived access
        token via ``POST /api/v2/oauth/token`` (the client secret alone is not
        accepted as a Bearer token), then reads the client's own key record via
        ``GET /api/v2/tailnet/-/keys/{keyId}`` using that access token, where
        ``keyId`` is the OAuth client's ID.
        """
        access_token = self._get_access_token()
        decoded = self._request_object(
            "GET",
            _KEY_PATH.format(key_id=urllib.parse.quote(self._client_id, safe="")),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return RootClientInfo(
            id=str(decoded.get("id", self._client_id)),
            key_type=decoded.get("keyType"),
            created=decoded.get("created"),
            scopes=list(decoded.get("scopes") or []),
            user_id=decoded.get("userId"),
            tags=list(decoded.get("tags") or []),
        )

    def mint_child_client(
        self,
        *,
        tags: list[str],
        scopes: list[str],
        description: str = DEFAULT_CHILD_DESCRIPTION,
    ) -> MintedClientInfo:
        """Mint a scoped, pre-authorized child OAuth client.

        Exchanges the OAuth client credentials for a short-lived access token,
        then creates a child client via ``POST /api/v2/tailnet/-/keys`` with
        ``keyType: "client"`` and ``preauthorized: true``.
        """
        access_token = self._get_access_token()
        body = json.dumps(
            {
                "keyType": "client",
                "preauthorized": True,
                "description": description,
                "tags": tags,
                "scopes": scopes,
            }
        )
        decoded = self._request_object(
            "POST",
            _KEYS_PATH,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            body=body,
        )
        key_id = decoded.get("id")
        key = decoded.get("key")
        if not key_id or not isinstance(key_id, str):
            raise TailscaleAPIError("mint response did not contain a key id")
        if not key or not isinstance(key, str):
            raise TailscaleAPIError("mint response did not contain a key secret")
        return MintedClientInfo(
            id=key_id,
            key=key,
            key_type=decoded.get("keyType"),
            created=decoded.get("created"),
            scopes=list(decoded.get("scopes") or []),
            tags=list(decoded.get("tags") or []),
        )

    def revoke_child_client(self, *, key_id: str) -> None:
        """Revoke a child OAuth client by key ID.

        Exchanges the OAuth client credentials for a short-lived access token,
        then deletes the child client via ``DELETE /api/v2/tailnet/-/keys/{keyId}``.
        The success response body is ``null``.
        """
        access_token = self._get_access_token()
        self._request(
            "DELETE",
            _KEY_PATH.format(key_id=urllib.parse.quote(key_id, safe="")),
            headers={"Authorization": f"Bearer {access_token}"},
        )


def get_root_client_info(state: CharmState) -> RootClientInfo:
    """Fetch information about the root OAuth client for the given charm state.

    Validates the state and the resolved root-credential content
    (``state.root_credential_content``, expected to carry ``client-id`` and
    ``client-secret``), then queries the Tailscale API. Every failure mode is
    reported by raising a ``RootClientError`` subclass whose message is
    user-facing, so callers can map the single base type to an error.
    """
    client_id, client_secret = _resolve_tailscale_credentials(state)
    return TailscaleBackend(client_id, client_secret).get_root_client_info()


def mint_child_client(state: CharmState, *, scopes: list[str]) -> MintedClientInfo:
    """Mint a pre-authorized child OAuth client for the given charm state.

    Validates the state and resolved root credential, reads the parent
    client's tags (the child inherits the SAME tags as the parent), then mints
    a child client carrying those tags and the requested ``scopes`` (capped
    server-side to a subset of the parent's). Failure modes are reported by
    raising a ``RootClientError`` subclass whose message is user-facing.
    """
    client_id, client_secret = _resolve_tailscale_credentials(state)
    backend = TailscaleBackend(client_id, client_secret)
    parent = backend.get_root_client_info()
    return backend.mint_child_client(tags=parent.tags, scopes=scopes)


def revoke_child_client(state: CharmState, *, key_id: str) -> None:
    """Revoke a child OAuth client for the given charm state.

    Validates the state and resolved root credential, then deletes the child
    client identified by ``key_id``. Failure modes are reported by raising a
    ``RootClientError`` subclass whose message is user-facing.
    """
    client_id, client_secret = _resolve_tailscale_credentials(state)
    TailscaleBackend(client_id, client_secret).revoke_child_client(key_id=key_id)


def _resolve_tailscale_credentials(state: CharmState) -> tuple[str, str]:
    """Validate ``state`` and return the root ``(client-id, client-secret)``.

    Raises a ``RootClientError`` subclass whose message is user-facing for any
    invalid backend, missing/unreadable/incomplete root-credential state.
    """
    if state.backend != BACKEND_TAILSCALE:
        raise UnsupportedBackendError(state.backend)
    if state.root_credential is None:
        raise MissingRootCredentialError()
    if state.root_credential_content is None:
        raise UnreadableRootCredentialError()
    client_id = state.root_credential_content.get("client-id")
    client_secret = state.root_credential_content.get("client-secret")
    if not client_id or not client_secret:
        raise IncompleteRootCredentialError()
    return client_id, client_secret
