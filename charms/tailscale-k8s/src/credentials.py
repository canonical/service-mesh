# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Credential resolution for the Tailscale K8s operator charm.

Handles manual (Juju secret) credentials provided via the 'credentials' config option.
"""

import logging

import ops

LOGGER = logging.getLogger(__name__)


def resolve_credentials(charm: ops.CharmBase) -> tuple:
    """Resolve OAuth credentials from the manual (Juju secret) config source.

    Returns a (credentials, error) tuple. Exactly one is non-None:
    - (credentials_dict, None) on success, where credentials_dict has
      'client-id' and 'client-secret'.
    - (None, error_message) otherwise, with a message specific to the cause
      (nothing configured, secret not granted, missing fields, or a read error)
      so the failure is actionable rather than a generic "no credentials".

    Args:
        charm: The charm instance.
    """
    secret_id = charm.config.get("credentials")
    if not secret_id:
        return (None, "No credentials configured. Provide credentials via config.")

    try:
        secret = charm.model.get_secret(id=str(secret_id))
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
        {"client-id": content["client-id"], "client-secret": content["client-secret"]},
        None,
    )
