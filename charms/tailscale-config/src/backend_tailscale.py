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
_TOKEN_PATH = "/api/v2/oauth/token"


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


class TailscaleBackend:
    """A thin client for the subset of the Tailscale API this charm needs."""

    def __init__(self, host: str = TAILSCALE_API_HOST):
        self._host = host

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: str | None = None,
    ) -> dict:
        """Perform an HTTPS request and return the decoded JSON body.

        Raises ``TailscaleAPIError`` on transport errors, non-2xx responses, or
        bodies that are not valid JSON objects.
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
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TailscaleAPIError(f"invalid JSON in response to {method} {path}") from exc
        if not isinstance(decoded, dict):
            raise TailscaleAPIError(f"expected a JSON object in response to {method} {path}")
        return decoded

    def _get_access_token(self, client_id: str, client_secret: str) -> str:
        """Exchange OAuth client credentials for a short-lived access token.

        Performs the OAuth2 ``client_credentials`` grant against the Tailscale
        token endpoint and returns the ``access_token``. Raises
        ``TailscaleAPIError`` if the exchange fails or no token is returned.
        """
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        )
        decoded = self._request(
            "POST",
            _TOKEN_PATH,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        access_token = decoded.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise TailscaleAPIError("token endpoint response did not contain an access_token")
        return access_token

    def get_root_client_info(self, client_id: str, client_secret: str) -> RootClientInfo:
        """Return information about the root OAuth client.

        First exchanges the OAuth client credentials for a short-lived access
        token via ``POST /api/v2/oauth/token`` (the client secret alone is not
        accepted as a Bearer token), then reads the client's own key record via
        ``GET /api/v2/tailnet/-/keys/{keyId}`` using that access token, where
        ``keyId`` is the OAuth client's ID.
        """
        access_token = self._get_access_token(client_id, client_secret)
        decoded = self._request(
            "GET",
            _KEY_PATH.format(key_id=urllib.parse.quote(client_id, safe="")),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return RootClientInfo(
            id=str(decoded.get("id", client_id)),
            key_type=decoded.get("keyType"),
            created=decoded.get("created"),
            scopes=list(decoded.get("scopes") or []),
            user_id=decoded.get("userId"),
        )


def get_root_client_info(state: CharmState) -> RootClientInfo:
    """Fetch information about the root OAuth client for the given charm state.

    Validates the state and the resolved root-credential content
    (``state.root_credential_content``, expected to carry ``client-id`` and
    ``client-secret``), then queries the Tailscale API. Every failure mode is
    reported by raising a ``RootClientError`` subclass whose message is
    user-facing, so callers can map the single base type to an error.
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
    return TailscaleBackend().get_root_client_info(client_id, client_secret)
