# 0007 - split status tests off charm.py

## Feature
Test-only refactor. Status logic (`get_charm_status`) is pure over `CharmState`;
test it directly instead of via full Scenario runs.

## Main changes
- `tests/unit/test_tailscale_config.py` (new):
    - 6 status tests moved from `test_charm.py`, now direct `get_charm_status`
      calls. No `Context`/`State`/mocks. `_state()` helper for overrides.
    - +2 precedence tests: invalid-backend before missing-root-credential;
      tailscale never blocks on empty login-server.
- `tests/unit/test_charm.py`:
    - Dropped the 6 migrated status tests.
    - New `test_collect_status_surfaces_get_charm_status_result`: mocks
      `get_charm_status`, asserts handler surfaces its return.
