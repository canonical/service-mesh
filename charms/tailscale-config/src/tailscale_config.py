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


class CharmState(BaseModel):
    """Snapshot of the charm's inputs, collected once per hook."""

    backend: str
    """The control-plane backend, validated against ``VALID_BACKENDS``."""

    root_credential: str | None
    """URI of the Juju user secret holding the root credential, if set."""

    login_server: str | None
    """URL of the control plane, or ``None`` when left empty."""

    def has_valid_backend(self) -> bool:
        """Return whether ``backend`` names a supported control-plane backend."""
        return self.backend in VALID_BACKENDS


def get_charm_status(state: CharmState) -> ops.StatusBase:
    """Derive the unit status from the collected charm state."""
    if not state.has_valid_backend():
        return ops.BlockedStatus(
            f"invalid backend {state.backend!r}; "
            f"must be one of {', '.join(sorted(VALID_BACKENDS))}"
        )
    if state.root_credential is None:
        return ops.BlockedStatus("root-credential config is required")
    return ops.ActiveStatus()


# Control-plane API interaction logic (Tailscale / Headscale) will live here.
