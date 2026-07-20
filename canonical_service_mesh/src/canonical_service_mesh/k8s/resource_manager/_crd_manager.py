# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for CustomResourceDefinition manifests."""

import logging
from typing import Optional

from lightkube import ApiError, Client
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from ops import CharmBase

from ..types import LightkubeResourcesList
from ._resource_manager import KubernetesResourceManager, create_charm_default_labels

_ESTABLISHED_CONDITION = "Established"


class CustomResourceDefinitionManager:
    """Manage a manifest of CustomResourceDefinitions and report when they are Established.

    Composes a KubernetesResourceManager scoped to CustomResourceDefinition. Charms apply their
    own CRD manifests through reconcile() and gate controller startup on established(); a charm
    that does not need the readiness gate can simply skip the established() call.

    Args:
        charm: The charm instantiating this manager.
        lightkube_client: Lightkube Client for all k8s operations.
        scope: Label scope distinguishing this CRD set from others managed by the same charm.
        logger: Logger for log output.
    """

    def __init__(
        self,
        charm: CharmBase,
        lightkube_client: Client,
        scope: str,
        logger: Optional[logging.Logger] = None,
    ):
        self.log = logger or logging.getLogger(__name__)
        self._client = lightkube_client
        self._krm = KubernetesResourceManager(
            labels=create_charm_default_labels(charm.app.name, charm.model.name, scope=scope),
            resource_types={CustomResourceDefinition},
            lightkube_client=lightkube_client,
            logger=self.log,
        )

    def reconcile(self, resources: LightkubeResourcesList) -> None:
        """Reconcile the given CustomResourceDefinitions.

        Args:
            resources: The CustomResourceDefinition resources to apply.
        """
        self._krm.reconcile(resources)

    def delete(self, ignore_missing: bool = True) -> None:
        """Delete all CustomResourceDefinitions managed by this manager.

        Args:
            ignore_missing: Avoid raising 404 errors on deletion.
        """
        self._krm.delete(ignore_missing=ignore_missing)

    def established(self, resources: LightkubeResourcesList) -> bool:
        """Return True when every given CustomResourceDefinition reports Established.

        A CRD is Established once the API server has accepted it and begun serving its resources;
        creating custom resources before then races the API server and fails. A CRD that is
        missing or briefly unqueryable (the API server returns 404/429 while freshly applied
        CRDs initialise their storage) counts as not-yet-Established rather than an error, so a
        caller can defer cleanly instead of flipping to error state.

        Args:
            resources: The CustomResourceDefinition resources to check.
        """
        for crd in resources:
            name = crd.metadata.name  # pyright: ignore[reportAttributeAccessIssue]
            try:
                live = self._client.get(CustomResourceDefinition, name=name)
            except ApiError:
                self.log.debug("CRD %s not yet queryable", name)
                return False
            conditions = (live.status.conditions if live.status else None) or []
            if not any(
                condition.type == _ESTABLISHED_CONDITION and condition.status == "True"
                for condition in conditions
            ):
                self.log.debug("CRD %s not yet Established", name)
                return False
        return True
