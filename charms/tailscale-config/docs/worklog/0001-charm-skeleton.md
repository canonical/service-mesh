# 0001 - Charm skeleton (README + charmcraft.yaml)

## Main changes
- `charmcraft.yaml`: real title/summary/description/links; removed template `containers:`/`resources:`/`log-level`; dropped `assumes: k8s-api` (kept `juju >= 3.6`).
- Config: `backend` (`tailscale`|`headscale`), `login-server`, `root-credential` (`type: secret`).
- `provides: tailscale-credentials` (interface `tailscale_credentials`) for downstream credential distribution.
- `README.md`: workloadless credential-authority description + Usage; noted charm is optional.
- Made the charm truly workloadless: removed Pebble/container scaffolding from `src/charm.py`, which now only reports `ActiveStatus` via `collect-unit-status`.
- Dropped the `get_version()` placeholder from `src/tailscale_config.py`.
- Updated unit/integration tests to match.

