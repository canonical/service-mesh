# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Direct unit tests for the charm-free ``get_charm_status`` orchestrator."""

import ops

from tailscale_config import CharmState, get_charm_status

ROOT_CREDENTIAL_URI = "secret:cvh7kruupa1s46bqvuig"


def _state(**overrides) -> CharmState:
    """Return a leader state that reports active, with per-test overrides."""
    fields = {
        "backend": "tailscale",
        "root_credential": ROOT_CREDENTIAL_URI,
        "login_server": None,
        "is_leader": True,
        "peer_relation_available": True,
    }
    fields.update(overrides)
    return CharmState(**fields)


def test_active_status():
    """A leader with a root credential and peer relation reports active."""
    # Arrange:
    state = _state()

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert status == ops.ActiveStatus()
    assert status.message == ""


def test_non_leader_reports_standby():
    """A non-leader unit reports active standby and does no work."""
    # Arrange:
    state = _state(is_leader=False)

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert isinstance(status, ops.ActiveStatus)
    assert "standby" in status.message


def test_maintenance_without_peer_relation():
    """Without the peer relation the leader reports maintenance."""
    # Arrange:
    state = _state(peer_relation_available=False)

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert isinstance(status, ops.MaintenanceStatus)
    assert "peer relation" in status.message


def test_blocked_without_root_credential():
    """Without a root credential the charm blocks."""
    # Arrange:
    state = _state(root_credential=None)

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert isinstance(status, ops.BlockedStatus)
    assert "root-credential" in status.message


def test_blocked_on_invalid_backend():
    """An unrecognized backend blocks, even with a root credential set."""
    # Arrange:
    state = _state(backend="bogus")

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert isinstance(status, ops.BlockedStatus)
    assert "bogus" in status.message


def test_blocked_on_headscale_without_login_server():
    """The headscale backend blocks when no login-server is configured."""
    # Arrange:
    state = _state(backend="headscale", login_server=None)

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert isinstance(status, ops.BlockedStatus)
    assert "login-server" in status.message


def test_invalid_backend_takes_priority_over_missing_root_credential():
    """An invalid backend blocks before the missing root-credential check."""
    # Arrange:
    state = _state(backend="bogus", root_credential=None)

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert isinstance(status, ops.BlockedStatus)
    assert "bogus" in status.message


def test_tailscale_never_blocks_on_missing_login_server():
    """The tailscale backend resolves a default login-server and stays active."""
    # Arrange:
    state = _state(backend="tailscale", login_server=None)

    # Act:
    status = get_charm_status(state)

    # Assert:
    assert status == ops.ActiveStatus()


def test_is_ready_to_reconcile_when_ready():
    """A fully configured leader is ready to reconcile with no reason."""
    # Arrange:
    state = _state()

    # Act:
    ready, reason = state.is_ready_to_reconcile()

    # Assert:
    assert ready is True
    assert reason == ""


def test_is_ready_to_reconcile_not_leader():
    """A non-leader is not ready to reconcile."""
    # Arrange:
    state = _state(is_leader=False)

    # Act:
    ready, reason = state.is_ready_to_reconcile()

    # Assert:
    assert ready is False
    assert "leader" in reason


def test_is_ready_to_reconcile_invalid_backend():
    """An unrecognized backend is not ready to reconcile."""
    # Arrange:
    state = _state(backend="bogus")

    # Act:
    ready, reason = state.is_ready_to_reconcile()

    # Assert:
    assert ready is False
    assert "bogus" in reason


def test_is_ready_to_reconcile_without_root_credential():
    """A missing root credential blocks reconcile."""
    # Arrange:
    state = _state(root_credential=None)

    # Act:
    ready, reason = state.is_ready_to_reconcile()

    # Assert:
    assert ready is False
    assert "root credential" in reason


def test_is_ready_to_reconcile_without_peer_relation():
    """An absent peer relation blocks reconcile."""
    # Arrange:
    state = _state(peer_relation_available=False)

    # Act:
    ready, reason = state.is_ready_to_reconcile()

    # Assert:
    assert ready is False
    assert "peer relation" in reason


def test_is_ready_to_reconcile_headscale_without_login_server():
    """The headscale backend without a login-server blocks reconcile."""
    # Arrange:
    state = _state(backend="headscale", login_server=None)

    # Act:
    ready, reason = state.is_ready_to_reconcile()

    # Assert:
    assert ready is False
    assert "login-server" in reason
