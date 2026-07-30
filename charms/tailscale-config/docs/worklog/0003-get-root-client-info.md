# 0003 - get-root-client-info action + OAuth token exchange

## Feature
`juju run tailscale-config/leader get-root-client-info` reports info about the
root OAuth client configured via the `root-credential` Juju user secret
(tailscale backend only). Read-only; prints no secret material.

## Main changes
- new `get-root-client-info` action (no params)
- `charm.py`: 
    - `_collect_state` resolves the secret via `_resolve_secret`; 
    - `_on_get_root_client_info` calls module-level `get_root_client_info(state)`
- `tailscale_config.py`: 
    - `CharmState` carries resolved `root_credential_content` (`client-id` + `client-secret`); 
    - backend never reads Juju secrets.
- `backend_tailscale.py`: 
    - stdlib-only HTTP (`http.client`, no new deps). 
    - Typed `RootClientError` hierarchy.
    - `TailscaleBackend` as API wrapper class
    - Module-level `get_root_client_info(state)` does all input validation.
    - OAuth flow: `_get_access_token` does the `client_credentials` exchange, then `GET /api/v2/tailnet/-/keys/{keyId}` with `Bearer <access_token>`.
    - `RootClientInfo` for typed results
- backend tests: two-call flow mocked via `getresponse.side_effect` (`_connection_for_flow`)


