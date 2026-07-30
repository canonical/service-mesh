# 0002 - Reconciler pattern + charm state

## Main changes
- Added `CharmState`, and module-level `get_charm_status(state)`.
- `CharmState` is permissive: every field parses; invalid input surfaces as blocked status, not a crash. `login_server` empty -> `None`; `root_credential` holds config secret URI or `None`.
- `get_charm_status`: blocks on invalid backend, then on missing root credential, else active.
- `src/charm.py`: reconciler pattern. `_collect_state()` builds `CharmState` from config; `_reconcile()` runs on every hook, `_on_collect_status` reports `get_charm_status(state)`.
- `pyproject.toml`: added `pydantic>=2`; `uv.lock` updated.
- Unit tests: active (valid backend + root-credential), blocked (no root-credential), blocked (invalid backend), `_collect_state` empty login-server -> `None`.
- Integration test: add/grant fake `root-credential` secret + set `backend` config so the charm reaches active.
