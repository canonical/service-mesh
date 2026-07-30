# 0004 - child-client mint + revoke (backend layer)

## Feature
`backend_tailscale.py` can now mint pre-authorized child OAuth clients and
revoke them via the Tailscale API. Backend-only; no charm/relation wiring yet.

## Main changes
- `backend_tailscale.py`:
    - `RootClientInfo`: new `tags` field (populated from GET-key response).
    - `MintedClientInfo`: typed mint result, carries the new credentials.
    - `TailscaleBackend.mint_child_client(...)`: token exchange then `POST` request 
    - `TailscaleBackend.revoke_child_client(...)`: token exchange then `DELETE` request.
    - `_request` now returns `dict | None` (empty body or JSON `null` ->
      `None`; arrays/scalars still rejected); `_request_object` wraps it for
      the dict-consumers.
    - `_get_access_token` caches the token per-instance (tokens comfortably
      outlive a hook, so no expiry tracking).
    - `TailscaleBackend(client_id, client_secret)` holds the root credentials;
    - `_resolve_tailscale_credentials(state)`: shared guard chain
    - Module-level `mint_child_client(state, *, scopes)` reads parent tags via
      `get_root_client_info` then mints with the SAME tags (spec: child inherits
      parent tags). 
    - Module-level `revoke_child_client(state, *, key_id)`.
- tests: 
    - adjustments to changes
    - mint/revoke methods + module-level flows
