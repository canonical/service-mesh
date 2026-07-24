#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import json
import logging

import ops
from canonical_service_mesh.interfaces.tailscale_credentials import (
    ProviderAppData,
    TailscaleCredentials,
    TailscaleCredentialsProvider,
)

from backend_tailscale import (
    DEFAULT_CHILD_SCOPES,
    RootClientError,
    get_root_client_info,
    mint_child_client,
    revoke_child_client,
)
from tailscale_config import CharmState, get_charm_status

logger = logging.getLogger(__name__)

PEER_RELATION_NAME = "credentials-map"
"""Name of the provider-internal peer relation holding the credential map."""

CREDENTIAL_MAP_KEY = "credential-map"
"""Peer app-databag key under which the ``relation-id -> key_id`` map lives."""


class TailscaleConfigCharm(ops.CharmBase):
    """Charm the application.

    tailscale-config is a workloadless charm: it runs no Pebble services and
    manages no workload container. Its behavior is entirely credential
    minting/distribution.

    It follows a reconciler pattern: every observed hook runs the idempotent
    ``_reconcile`` method, which first collects the charm state and then
    performs the steps needed to converge on that state.
    """

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.credentials = TailscaleCredentialsProvider(self.model.relations, self.app)
        framework.observe(self.on.config_changed, self._reconcile)
        framework.observe(self.on.start, self._reconcile)
        framework.observe(self.on.update_status, self._reconcile)
        framework.observe(self.on.secret_changed, self._reconcile)
        framework.observe(self.on["tailscale-credentials"].relation_created, self._reconcile)
        framework.observe(self.on["tailscale-credentials"].relation_changed, self._reconcile)
        framework.observe(self.on["tailscale-credentials"].relation_broken, self._reconcile)
        framework.observe(self.on[PEER_RELATION_NAME].relation_created, self._reconcile)
        framework.observe(self.on[PEER_RELATION_NAME].relation_changed, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on.get_root_client_info_action, self._on_get_root_client_info)

    def _collect_state(self) -> CharmState:
        """Collect the charm's inputs into a validated state snapshot."""
        root_credential = str(self.config.get("root-credential") or "") or None
        return CharmState(
            backend=str(self.config["backend"]),
            root_credential=root_credential,
            root_credential_content=self._resolve_secret(root_credential),
            login_server=(str(self.config.get("login-server") or "") or None),
            credential_relation_ids=[rel.id for rel in self.credentials.relations],
            credential_map=self._read_credential_map(),
            is_leader=self.unit.is_leader(),
            peer_relation_available=self._peer_relation() is not None,
        )

    def _resolve_secret(self, uri: str | None) -> dict[str, str] | None:
        """Resolve a Juju secret URI to its content, or ``None`` if unavailable."""
        if uri is None:
            return None
        try:
            return self.model.get_secret(id=uri).get_content(refresh=True)
        except ops.SecretNotFoundError:
            logger.debug("secret %r not found or not granted to this application", uri)
            return None

    def _peer_relation(self) -> ops.Relation | None:
        """Return the provider-internal peer relation, if present."""
        return self.model.get_relation(PEER_RELATION_NAME)

    def _read_credential_map(self) -> dict[str, str]:
        """Read the ``relation-id -> key_id`` map from the peer app databag."""
        peer = self._peer_relation()
        if peer is None:
            return {}
        raw = peer.data[self.app].get(CREDENTIAL_MAP_KEY)
        return json.loads(raw) if raw else {}

    def _write_credential_map(self, credential_map: dict[str, str]) -> None:
        """Write the ``relation-id -> key_id`` map to the peer app databag.

        Only the leader owns this write; callers must hold leadership and
        ensure the peer relation is present.
        """
        peer = self._peer_relation()
        assert peer is not None  # guaranteed by the _reconcile guard
        peer.data[self.app][CREDENTIAL_MAP_KEY] = json.dumps(credential_map, sort_keys=True)

    def _reconcile(self, _: ops.EventBase) -> None:
        """Idempotently converge the charm on its collected state.

        Runs on every observed hook. Mints one child credential per
        ``tailscale-credentials`` relation, distributes it as a granted Juju
        secret, and revokes children whose relation has gone away. The peer
        relation's app databag is the source of truth for idempotency and
        revoke-on-removal.
        """
        state = self._collect_state()
        ready, reason = state.is_ready_to_reconcile()
        if not ready:
            logger.debug("skipping reconcile: %s", reason)
            return

        credential_map = dict(state.credential_map)
        credential_map = self._reconcile_mint(state, credential_map)
        credential_map = self._reconcile_revoke(state, credential_map)
        self._write_credential_map(credential_map)

    def _reconcile_mint(self, state: CharmState, credential_map: dict[str, str]) -> dict[str, str]:
        """Mint + distribute a child credential for each active relation.

        Returns the credential map updated with any newly minted children.
        Idempotent: a relation already recorded in ``credential_map`` is
        skipped (already minted, granted, and published on a prior hook).
        """
        for relation in self.credentials.relations:
            key = str(relation.id)
            if key in credential_map:
                continue
            credential_map[key] = self._mint_credential_for_relation(state, relation)
        return credential_map

    def _mint_credential_for_relation(self, state: CharmState, relation: ops.Relation) -> str:
        """Mint a child credential for one relation and distribute it.

        Adds the secret as a granted Juju secret and publishes the provider
        app data. Returns the minted child's key id for the credential map.
        """
        login_server = state.resolve_login_server()
        assert login_server is not None  # guaranteed by the _reconcile guard
        minted = mint_child_client(state, scopes=DEFAULT_CHILD_SCOPES)
        content = TailscaleCredentials.model_validate(
            {"auth-key": minted.key, "client-id": minted.id}
        ).to_secret_content()
        secret = self.app.add_secret(content)
        secret.grant(relation)
        self.credentials.publish(
            relation,
            ProviderAppData(
                secret_id=secret.id,
                login_server=login_server,
                tags=minted.tags,
            ),
        )
        logger.info("minted child credential %s for relation %s", minted.id, relation.id)
        return minted.id

    def _reconcile_revoke(
        self, state: CharmState, credential_map: dict[str, str]
    ) -> dict[str, str]:
        """Revoke children whose relation is no longer active.

        Returns the credential map with departed entries removed. A revoke
        failure against the control-plane API is fatal: the entry is left in
        place and the exception propagates so Juju retries the hook.
        """
        active = {str(rel_id) for rel_id in state.credential_relation_ids}
        for key in list(credential_map):
            if key in active:
                continue
            key_id = credential_map[key]
            revoke_child_client(state, key_id=key_id)
            del credential_map[key]
            logger.info("revoked child credential %s for departed relation %s", key_id, key)
        return credential_map

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the unit status."""
        event.add_status(get_charm_status(self._collect_state()))

    def _on_get_root_client_info(self, event: ops.ActionEvent) -> None:
        """Print information about the root OAuth client."""
        try:
            info = get_root_client_info(self._collect_state())
        except RootClientError as exc:
            logger.warning("failed to fetch root OAuth client info: %s", exc)
            event.fail(str(exc))
            return

        event.set_results(
            {
                "id": info.id,
                "key-type": info.key_type or "",
                "created": info.created or "",
                "scopes": ", ".join(info.scopes),
                "user-id": info.user_id or "",
            }
        )


if __name__ == "__main__":  # pragma: nocover
    ops.main(TailscaleConfigCharm)
