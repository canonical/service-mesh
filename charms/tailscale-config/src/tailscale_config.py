# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Functions for interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging

import ops
from pydantic import BaseModel

logger = logging.getLogger(__name__)

BACKEND_TAILSCALE = "tailscale"
"""The Tailscale SaaS control-plane backend."""

BACKEND_HEADSCALE = "headscale"
"""The self-hosted Headscale control-plane backend."""

VALID_BACKENDS = frozenset({BACKEND_TAILSCALE, BACKEND_HEADSCALE})
"""The set of control-plane backends this charm can mint credentials against."""

TAILSCALE_LOGIN_SERVER = "https://login.tailscale.com"
"""Well-known Tailscale SaaS control-plane URL, substituted for the
``tailscale`` backend so ``login-server`` is never empty on the wire."""


class CharmState(BaseModel):
    """Snapshot of the charm's inputs, collected once per hook."""

    backend: str
    """The control-plane backend, validated against ``VALID_BACKENDS``."""

    root_credential: str | None
    """URI of the Juju user secret holding the root credential, if set."""

    root_credential_content: dict[str, str] | None = None
    """Resolved content of the root credential secret, or ``None`` if unset or
    unreadable. For the ``tailscale`` backend this carries ``client-id`` and
    ``client-secret``."""

    login_server: str | None
    """URL of the control plane, or ``None`` when left empty."""

    credential_relation_ids: list[int] = []
    """IDs of the active ``tailscale-credentials`` relations, one child
    credential per relation."""

    credential_map: dict[str, str] = {}
    """Provider-internal ``relation-id -> key_id`` map of minted children, read
    from the peer relation's app databag. Source of truth for idempotent mint
    and revoke-on-removal."""

    is_leader: bool = False
    """Whether this unit is the application leader; only the leader mints,
    revokes, and writes the peer credential map."""

    peer_relation_available: bool = False
    """Whether the provider-internal peer relation is present, i.e. the
    credential map can be read and written."""

    def has_valid_backend(self) -> bool:
        """Return whether ``backend`` names a supported control-plane backend."""
        return self.backend in VALID_BACKENDS

    def resolve_login_server(self) -> str | None:
        """Resolve the ``login-server`` URL to publish, or ``None`` if unresolvable.

        Tailscale: the configured URL if set, else the well-known SaaS URL.
        Headscale: the configured URL, which is required; ``None`` when unset.
        """
        if self.backend == BACKEND_TAILSCALE:
            return self.login_server or TAILSCALE_LOGIN_SERVER
        return self.login_server

    def is_ready_to_reconcile(self) -> tuple[bool, str]:
        """Return whether reconcile can run, with a reason when it should not.

        The reason is empty when ready, otherwise a human-readable explanation
        of the first unmet precondition, suitable for debug logging.
        """
        if not self.is_leader:
            return False, "not leader"
        if not self.has_valid_backend():
            return False, f"invalid backend {self.backend!r}"
        if self.resolve_login_server() is None:
            return False, "login-server not resolvable"
        if self.root_credential is None:
            return False, "root credential not set"
        if not self.peer_relation_available:
            return False, "peer relation not yet available"
        return True, ""


def get_charm_status(state: CharmState) -> ops.StatusBase:
    """Derive the unit status from the collected charm state."""
    if not state.is_leader:
        return ops.ActiveStatus("standby (non-leader)")
    if not state.has_valid_backend():
        return ops.BlockedStatus(
            f"invalid backend {state.backend!r}; "
            f"must be one of {', '.join(sorted(VALID_BACKENDS))}"
        )
    if state.resolve_login_server() is None:
        return ops.BlockedStatus("login-server config is required for the headscale backend")
    if state.root_credential is None:
        return ops.BlockedStatus("root-credential config is required")
    if not state.peer_relation_available:
        return ops.MaintenanceStatus("waiting for the peer relation")
    return ops.ActiveStatus()
