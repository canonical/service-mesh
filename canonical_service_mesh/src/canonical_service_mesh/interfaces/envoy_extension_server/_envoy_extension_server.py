# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy extension-server interface implementation.

Wires an Envoy Gateway control plane (requirer) to a server that implements
Envoy Gateway's Extension Server protocol (provider) — today, the Envoy AI
Gateway controller. The provider advertises where its extension-server gRPC
endpoint lives; the requirer consumes that to configure EG's ``extensionManager``
and advertises its own controller identity back so the provider can gate itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ops.framework import Object
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from ops import CharmBase

DEFAULT_RELATION_NAME = "envoy-extension-server"

# Envoy Gateway's Extension Server protocol default gRPC port.
DEFAULT_EXTENSION_SERVER_PORT = "1063"

logger = logging.getLogger(__name__)


class ExtensionServerData(BaseModel):
    """Provider-side databag model for the envoy-extension-server relation.

    Each field maps to a top-level key in the provider's application databag.
    Use ``ops.Relation.load`` / ``ops.Relation.save`` to (de)serialise.
    """

    model_config = ConfigDict(frozen=True)

    extension_server_fqdn: str | None = Field(
        default=None,
        description="Cluster-internal FQDN of the extension-server gRPC service.",
    )
    extension_server_port: str | None = Field(
        default=None,
        description="Port of the extension-server gRPC service (Envoy Gateway default 1063).",
    )

    @field_validator("extension_server_port")
    @classmethod
    def _validate_port(cls, port: str | None) -> str | None:
        if port is None:
            return port
        try:
            int(port)
        except ValueError:
            msg = f"extension_server_port must be convertible to an integer, got {port!r}"
            raise ValueError(msg) from None
        return port


class ControllerIdentityData(BaseModel):
    """Requirer-side databag model for the envoy-extension-server relation.

    Carries the Envoy Gateway control plane's identity so the provider can gate
    itself to the correct GatewayClass and namespace.
    """

    model_config = ConfigDict(frozen=True)

    controller_name: str | None = Field(
        default=None,
        description="The Envoy Gateway controllerName / GatewayClass the extension targets.",
    )
    namespace: str | None = Field(
        default=None,
        description="The namespace the Envoy Gateway control plane runs in.",
    )


class ExtensionServerProvider(Object):
    """Provider side of the envoy_extension_server interface.

    Used by the extension server (e.g. the AI Gateway controller) to advertise
    the address of its extension-server gRPC endpoint and to read the Envoy
    Gateway control plane's identity from the requirer.
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """Initialize the ExtensionServerProvider.

        Args:
            charm: The charm that owns this provider.
            relation_name: Name of the relation (default: "envoy-extension-server").
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    def publish_data(
        self,
        extension_server_fqdn: str,
        extension_server_port: str = DEFAULT_EXTENSION_SERVER_PORT,
    ) -> None:
        """Publish the extension-server address to all related applications.

        Args:
            extension_server_fqdn: Cluster-internal FQDN of the extension-server gRPC service.
            extension_server_port: Port of the extension-server gRPC service.
        """
        if not self._charm.unit.is_leader():
            logger.debug("Not leader, skipping extension-server data publication")
            return

        data = ExtensionServerData(
            extension_server_fqdn=extension_server_fqdn,
            extension_server_port=extension_server_port,
        )
        for relation in self._charm.model.relations.get(self._relation_name, []):
            relation.save(data, self._charm.app)

    def get_controller_identity(self) -> ControllerIdentityData | None:
        """Read the Envoy Gateway control plane's identity from the requirer.

        Returns:
            The requirer's ControllerIdentityData if a single relation has
            published valid data, else None.
        """
        relations = self._charm.model.relations.get(self._relation_name, [])
        for relation in relations:
            if not relation.app:
                continue
            try:
                return relation.load(ControllerIdentityData, relation.app)
            except Exception:
                logger.exception("Failed to parse controller identity from %s", relation.app.name)
        return None


class ExtensionServerRequirer(Object):
    """Requirer side of the envoy_extension_server interface.

    Used by the Envoy Gateway control plane to read the extension-server address
    it must configure EG's ``extensionManager`` with, and to publish its own
    controller identity so the provider can gate itself.
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """Initialize the ExtensionServerRequirer.

        Args:
            charm: The charm that owns this requirer.
            relation_name: Name of the relation (default: "envoy-extension-server").
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    @property
    def is_ready(self) -> bool:
        """Whether the provider has published a usable extension-server address.

        Returns:
            True if the related provider has published both
            extension_server_fqdn and extension_server_port.
        """
        return self.get_extension_server_data() is not None

    def publish_controller_identity(
        self,
        controller_name: str,
        namespace: str,
    ) -> None:
        """Publish this control plane's identity to all related applications.

        Args:
            controller_name: The EG controllerName / GatewayClass the extension targets.
            namespace: The namespace the EG control plane runs in.
        """
        if not self._charm.unit.is_leader():
            logger.debug("Not leader, skipping controller identity publication")
            return

        data = ControllerIdentityData(controller_name=controller_name, namespace=namespace)
        for relation in self._charm.model.relations.get(self._relation_name, []):
            relation.save(data, self._charm.app)

    def get_extension_server_data(self) -> ExtensionServerData | None:
        """Read the provider's extension-server address.

        Only data with both ``extension_server_fqdn`` and
        ``extension_server_port`` present is treated as ready.

        Returns:
            The provider's ExtensionServerData if available and complete, else None.
        """
        relations = self._charm.model.relations.get(self._relation_name, [])
        for relation in relations:
            if not relation.app:
                continue
            try:
                data = relation.load(ExtensionServerData, relation.app)
            except Exception:
                logger.exception(
                    "Failed to parse extension-server data from %s", relation.app.name
                )
                continue
            if data.extension_server_fqdn and data.extension_server_port:
                return data
        return None
