# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Resolve Tailscale credentials from charm config or relation data."""

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
    """Credentials and options passed to the Tailscale client."""

    auth_key: str
    login_server: str
    tags: tuple[str, ...]
    ephemeral: bool


def resolve_credentials(
    charm: ops.CharmBase,
) -> tuple[ResolvedCredentials | None, str | None]:
    """Resolve exactly one of the supported credential sources."""
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
        "No credentials configured. Provide the 'credentials' config option or "
        "integrate with tailscale-config.",
    )


def _resolve_from_config(
    charm: ops.CharmBase, secret_id: str
) -> tuple[ResolvedCredentials | None, str | None]:
    """Resolve a user-owned auth key from a Juju secret."""
    try:
        content = charm.model.get_secret(id=secret_id).get_content(refresh=True)
    except ops.SecretNotFoundError:
        return (
            None,
            "Credentials secret not found; grant it to this application "
            "(juju grant-secret).",
        )
    except ops.ModelError as error:
        LOGGER.error("Failed to read credentials secret: %s", error)
        return None, f"Cannot read credentials secret: {error}"

    auth_key = content.get("auth-key")
    if not auth_key:
        return None, "Credentials secret is missing required field: auth-key"

    return (
        ResolvedCredentials(
            auth_key=auth_key,
            login_server=str(charm.config["login-server"]),
            tags=_parse_tags(str(charm.config["advertise-tags"])),
            ephemeral=bool(charm.config["ephemeral"]),
        ),
        None,
    )


def _resolve_from_relation(
    charm: ops.CharmBase, relation: ops.Relation
) -> tuple[ResolvedCredentials | None, str | None]:
    """Resolve a provider-owned auth key from tailscale-config."""
    requirer = TailscaleCredentialsRequirer(charm.model.relations, charm.app)
    provider_data = requirer.get_provider_data(relation)
    if provider_data is None or not provider_data.is_ready_for_use():
        return None, "Waiting for credentials from tailscale-config."

    assert provider_data.secret_id is not None
    assert provider_data.login_server is not None
    try:
        content = charm.model.get_secret(id=provider_data.secret_id).get_content(refresh=True)
    except ops.SecretNotFoundError:
        return None, "Credentials secret from tailscale-config is not yet available."
    except ops.ModelError as error:
        LOGGER.error("Failed to read relation credentials secret: %s", error)
        return None, f"Cannot read credentials secret from tailscale-config: {error}"

    try:
        credentials = TailscaleCredentials.model_validate(content)
    except ValueError as error:
        LOGGER.error("Credentials secret from tailscale-config is invalid: %s", error)
        return None, "Credentials secret from tailscale-config is invalid."

    return (
        ResolvedCredentials(
            auth_key=credentials.auth_key,
            login_server=provider_data.login_server,
            tags=tuple(provider_data.tags or ()),
            ephemeral=bool(charm.config["ephemeral"]),
        ),
        None,
    )


def _parse_tags(value: str) -> tuple[str, ...]:
    return tuple(tag.strip() for tag in value.split(",") if tag.strip())
