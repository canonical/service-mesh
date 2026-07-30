# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Credential resolution for the Tailscale K8s operator charm.

Two mutually exclusive credential sources are supported:

- Manual mode: a Juju secret provided via the ``credentials`` config option,
  carrying ``client-id`` and ``client-secret`` fields, with the control-plane
  URL supplied separately by the ``login-server`` config option.
- Relation mode: the ``tailscale-credentials`` relation to ``tailscale-config``,
  which mints a scoped child credential and distributes it (plus the
  ``login-server``) via the ``tailscale_credentials`` interface library.

If both a ``credentials`` config secret and the relation are present, the charm
blocks rather than picking a winner.
"""

import logging
from dataclasses import dataclass

import ops
from canonical_service_mesh.interfaces.tailscale_credentials import (
    DEFAULT_RELATION_NAME,
    TailscaleCredentials,
    TailscaleCredentialsRequirer,
)

LOGGER = logging.getLogger(__name__)

RELATION_NAME = DEFAULT_RELATION_NAME


@dataclass(frozen=True)
class ResolvedCredentials:
    """Effective credentials for the operator, from whichever source resolved.

    The operator authenticates with an OAuth client id/secret pair. In relation
    mode the child OAuth client secret is carried as ``auth-key`` and maps to
    ``client_secret`` here. ``login_server`` is the control-plane URL (empty for
    Tailscale SaaS).
    """

    client_id: str
    client_secret: str
    login_server: str

    def to_workload(self) -> dict:
        """Return the credential dict expected by the workload push helper."""
        return {"client-id": self.client_id, "client-secret": self.client_secret}


def resolve_credentials(charm: ops.CharmBase) -> tuple:
    """Resolve OAuth credentials from config or the tailscale-credentials relation.

    Returns a ``(credentials, error)`` tuple. Exactly one is non-None:
    - ``(ResolvedCredentials, None)`` on success.
    - ``(None, error_message)`` otherwise, with a message specific to the cause
      (nothing configured, both sources present, secret not granted, missing
      fields, or a read error) so the failure is actionable.

    Args:
        charm: The charm instance.
    """
    config_secret_id = charm.config.get("credentials")
    relation = charm.model.get_relation(RELATION_NAME)

    if config_secret_id and relation is not None:
        return (
            None,
            "Both the 'credentials' config option and the tailscale-credentials "
            "relation are present; remove one.",
        )

    if relation is not None:
        return _resolve_from_relation(charm, relation)

    if config_secret_id:
        return _resolve_from_config(charm, str(config_secret_id))

    return (
        None,
        "No credentials configured. Provide credentials via the 'credentials' "
        "config option or the tailscale-credentials relation.",
    )


def _resolve_from_config(charm: ops.CharmBase, secret_id: str) -> tuple:
    """Resolve credentials from the manual (Juju secret) config source."""
    try:
        secret = charm.model.get_secret(id=secret_id)
        content = secret.get_content(refresh=True)
    except ops.SecretNotFoundError:
        return (
            None,
            "Credentials secret not found; grant it to this application "
            "(juju grant-secret).",
        )
    except ops.ModelError as e:
        LOGGER.error("Failed to read credentials secret: %s", e)
        return (None, f"Cannot read credentials secret: {e}")

    missing = [
        field
        for field in ("client-id", "client-secret")
        if not content.get(field)
    ]
    if missing:
        return (
            None,
            f"Credentials secret is missing required field(s): {', '.join(missing)}",
        )

    return (
        ResolvedCredentials(
            client_id=content["client-id"],
            client_secret=content["client-secret"],
            login_server=str(charm.config.get("login-server", "")),
        ),
        None,
    )


def _resolve_from_relation(charm: ops.CharmBase, relation: ops.Relation) -> tuple:
    """Resolve credentials from the tailscale-credentials relation.

    Reads the provider's non-secret app data (secret URI + login-server), then
    fetches and validates the granted Juju secret content.
    """
    requirer = TailscaleCredentialsRequirer(charm.model.relations, charm.app)
    provider_data = requirer.get_provider_data(relation)
    if provider_data is None or not provider_data.is_ready_for_use():
        return (None, "Waiting for credentials from the tailscale-credentials relation.")

    # is_ready_for_use guarantees both secret_id and login_server are set.
    assert provider_data.secret_id is not None
    assert provider_data.login_server is not None

    try:
        content = charm.model.get_secret(id=provider_data.secret_id).get_content(refresh=True)
    except ops.SecretNotFoundError:
        return (None, "Credentials secret from the relation is not yet available.")
    except ops.ModelError as e:
        LOGGER.error("Failed to read credentials secret from relation: %s", e)
        return (None, f"Cannot read credentials secret from relation: {e}")

    try:
        credentials = TailscaleCredentials.model_validate(content)
    except Exception as e:  # noqa: BLE001 - reported as blocked status
        LOGGER.error("Credentials secret from relation is invalid: %s", e)
        return (None, "Credentials secret from the relation is invalid.")

    return (
        ResolvedCredentials(
            client_id=credentials.client_id,
            client_secret=credentials.auth_key,
            login_server=provider_data.login_server,
        ),
        None,
    )
