# 0006 - downstream tailscale-credentials relation (provider wiring)

## Feature
Provider side of the `tailscale-credentials` relation wired into the reconciler:
mint one child credential per relation, distribute as a granted Juju secret,
revoke on relation removal. Backed by a provider-internal peer relation.

## Main changes
- `charmcraft.yaml`:
    - Added `peers.credentials-map` (interface `tailscale_config_peers`)
- `tailscale_config.py`:
    - New fileds and helper methods for `CharmState` to support new functionality.
    - `get_charm_status` explicit precedence of different statuses.
- `backend_tailscale.py`: define a minimal `DEFAULT_CHILD_SCOPES`
- `charm.py`:
    - `TailscaleCredentialsProvider` from the interface lib; observe
      `tailscale-credentials`.
    - Peer-map read/write helpers (JSON in peer app databag; read/crash on bad
      data, internal so no defensive parsing).
    - `_reconcile`:
      - guards on `CharmState` only 
      - mint+grant+publish per new relation
      - revoke children whose relation departed.
      - API errors propagates -> Juju retries hook.
- corresponding unit tests