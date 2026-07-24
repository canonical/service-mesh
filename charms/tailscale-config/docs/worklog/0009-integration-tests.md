# 0009 - integration tests with credential-verifying requirer

## Feature
Prove minted credentials work end-to-end against the live Tailscale API.

## Main changes
- `tests/integration/dummy-requirer/`: minimal requirer charm. Reads the minted
  credential, verifies it via one OAuth token exchange, goes active. One-shot:
  result persisted in `StoredState`, so no repeat API calls.
- `tests/integration/conftest.py`: `charm`/`dummy_charm` fixtures pack via
  `charmcraft pack` (`CHARM_PATH` still overrides); `tailscale_credentials`
  fixture reads env, skips if unset.
- `tests/integration/test_charm.py`: `test_credentials_flow` deploys both,
  integrates, waits `all_active`.
- `tox.ini`: pass `TAILSCALE_CLIENT_ID`/`TAILSCALE_CLIENT_SECRET` to integration.
