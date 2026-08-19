# 0008 - extract reconcile guards into CharmState

## Feature
Collapse the five `if`-guards in `_reconcile` into one `CharmState` predicate.

## Main changes
- `tailscale_config.py`: new `CharmState.is_ready_to_reconcile() -> (bool, str)`.
  Same check order as `get_charm_status`. Reason string for debug logging.
- `charm.py`: `_reconcile` guards replaced by one call; single debug log.
- `tests/unit/test_tailscale_config.py`: +6 direct tests. 100% coverage.
