# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tailscale credentials interface implementation.

Thin Juju interface library for the ``tailscale-credentials`` relation. The
provider mints a per-relation credential against the control-plane API
and distributes it to the downstream charm as a Juju charm secret; it revokes
it on relation removal.

This library is deliberately thin: it contains only pydantic models, databag
read/write helpers, and secret-content build/parse helpers. It performs no live
``ops`` calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

if TYPE_CHECKING:
    from ops import Application, Relation, RelationMapping

DEFAULT_RELATION_NAME = "tailscale-credentials"

logger = logging.getLogger(__name__)


class ProviderAppData(BaseModel):
    """Non-secret provider app databag for the ``tailscale-credentials`` relation.

    Published by the provider to the requirer. The sensitive credential itself
    travels as a Juju charm secret; only its URI (``secret_id``) is carried here.
    """

    secret_id: str | None = Field(
        default=None,
        description="URI of the granted credential secret.",
    )
    login_server: str | None = Field(
        default=None,
        description="Control-plane URL; never empty on the wire.",
    )
    tags: list[str] | None = Field(
        default=None,
        description=(
            "Tags carried by the credential; comma-separated on the wire. "
            "Provider -> requirer informational only (the requirer never supplies tags)."
        ),
    )

    @field_validator("login_server")
    @classmethod
    def _reject_empty_login_server(cls, value: str | None) -> str | None:
        """Reject an empty ``login_server`` (never empty on the wire)."""
        if value == "":
            msg = "login_server must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _decode_tags(cls, value: object) -> object:
        """Decode a comma-separated wire string into a list of tags."""
        if isinstance(value, str):
            stripped = (t.strip() for t in value.split(","))
            return [t for t in stripped if t]
        return value

    @field_serializer("tags")
    def _encode_tags(self, tags: list[str] | None) -> str | None:
        """Encode the tag list as a comma-separated wire string."""
        if tags is None:
            return None
        return ",".join(tags)

    def to_databag(self) -> dict[str, str]:
        """Serialize to a flat ``dict[str, str]`` for the relation databag.

        Returns:
            A flat ``dict[str, str]`` with wire-encoded values, ready to write
            to the provider app databag.
        """
        return self.model_dump(mode="json", by_alias=True, exclude_defaults=True, round_trip=True)

    def is_ready_for_use(self) -> bool:
        """Check whether this data represents a usable credential.

        Returns:
            True if both ``secret_id`` and ``login_server`` are set.
        """
        return self.secret_id is not None and self.login_server is not None


class TailscaleCredentials(BaseModel):
    """Credential secret content for the Tailscale backend."""

    model_config = ConfigDict(populate_by_name=True)

    auth_key: str = Field(
        alias="auth-key",
        description=(
            "Child OAuth client secret (``tskey-client-...``); passed to the operator / "
            "``tailscale up --auth-key``."
        ),
    )
    client_id: str = Field(
        alias="client-id",
        description=(
            "Child OAuth client id (== the minted key_id); the requirer's operator-tag "
            "self-check reads ``GET .../keys/{client-id}``."
        ),
    )

    def to_secret_content(self) -> dict[str, str]:
        """Serialize to a flat ``dict[str, str]`` for a Juju secret's content.

        Returns:
            A flat ``dict[str, str]`` suitable for the charm's ``add_secret``.
        """
        return self.model_dump(by_alias=True)


class TailscaleCredentialsProvider:
    """Provider side wrapper for the ``tailscale-credentials`` relation.

    The provider publishes the non-secret app databag (secret URI, login-server,
    tags). The charm owns the secret lifecycle, the peer map, and control-plane
    minting; it builds the secret content via
    :meth:`TailscaleCredentials.to_secret_content`.
    """

    def __init__(
        self,
        relation_mapping: RelationMapping,
        app: Application,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """Initialize the TailscaleCredentialsProvider.

        Args:
            relation_mapping: The charm's RelationMapping (typically self.model.relations).
            app: This application (the tailscale-config charm).
            relation_name: The name of the relation.
        """
        self._charm_relation_mapping = relation_mapping
        self._app = app
        self._relation_name = relation_name

    @property
    def relations(self) -> list[Relation]:
        """Return the relation instances for the monitored relation."""
        return self._charm_relation_mapping.get(self._relation_name, [])

    def publish(self, relation: Relation, data: ProviderAppData) -> None:
        """Publish the provider app data to a specific relation.

        Args:
            relation: A specific relation instance.
            data: The provider app data to publish. ``login_server`` must be
                non-empty (enforced by :class:`ProviderAppData`).
        """
        serialized = data.to_databag()
        relation.data[self._app].update(serialized)
        logger.debug("Published provider data: %s to relation: %s", serialized, relation)


class TailscaleCredentialsRequirer:
    """Requirer side wrapper for the ``tailscale-credentials`` relation.

    The requirer reads the non-secret provider data (secret URI, login-server,
    tags) via :meth:`get_provider_data`; the charm then fetches the secret
    content with ``get_secret`` and validates it with
    ``TailscaleCredentials.model_validate``. The requirer never supplies data on
    the wire.
    """

    def __init__(
        self,
        relation_mapping: RelationMapping,
        app: Application,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """Initialize the TailscaleCredentialsRequirer.

        Args:
            relation_mapping: The charm's RelationMapping (typically self.model.relations).
            app: This application.
            relation_name: The name of the relation.
        """
        self._charm_relation_mapping = relation_mapping
        self._app = app
        self._relation_name = relation_name

    @property
    def relations(self) -> list[Relation]:
        """Return the relation instances for the monitored relation."""
        return self._charm_relation_mapping.get(self._relation_name, [])

    def get_provider_data(self, relation: Relation) -> ProviderAppData | None:
        """Read and validate the provider's non-secret app data for the relation.

        Args:
            relation: A specific relation instance.

        Returns:
            A :class:`ProviderAppData` (secret URI + login-server + tags) if
            available and valid, else ``None``.
        """
        raw_data = getattr(relation, "data", {}).get(relation.app, {})
        if not raw_data:
            return None
        try:
            return ProviderAppData.model_validate(raw_data)
        except Exception:
            logger.debug("Failed to validate provider data", exc_info=True)
            return None

    def is_ready(self, relation: Relation) -> bool:
        """Check whether the provider has published a usable credential.

        Args:
            relation: A specific relation instance.

        Returns:
            True if provider data is present with both ``secret_id`` and
            ``login_server`` set.
        """
        provider_data = self.get_provider_data(relation)
        if provider_data is None:
            return False
        return provider_data.is_ready_for_use()
