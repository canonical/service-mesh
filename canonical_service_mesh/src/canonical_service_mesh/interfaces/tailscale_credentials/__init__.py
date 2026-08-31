# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tailscale credentials interface library.

This library provides the provider and requirer sides of the
``tailscale-credentials`` relation interface. The provider (``tailscale-config``)
mints a per-relation credential against the control-plane API and
distributes it to one downstream charm (``tailscale-k8s`` / ``tailscale-beacon``);
it revokes the credential when the relation is removed.

What is this library for?
=========================

The credential is sensitive, so it travels as a Juju charm secret rather than as
plaintext in the databag. The provider adds and grants the secret, then publishes
its URI (plus the non-secret ``login-server`` and ``tags``) on its app databag.
The requirer reads the URI and fetches the secret content on demand. This works
over cross-model relations: only the secret URI crosses the databag, while the
content is fetched via Juju's controller channel.

This library is deliberately thin. It contains only pydantic models and databag /
secret-content helpers and makes no live ``ops`` calls. The charm owns
the secret ``add_secret`` / ``grant`` / ``get_secret`` calls.

Provider usage (tailscale-config charm)::

    from canonical_service_mesh.interfaces.tailscale_credentials import (
        ProviderAppData,
        TailscaleCredentials,
        TailscaleCredentialsProvider,
    )

    class MyConfigCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.creds = TailscaleCredentialsProvider(self.model.relations, self.app)

        def _reconcile(self, relation):
            # Charm mints the child credential against the control plane, then:
            content = TailscaleCredentials(
                auth_key="tskey-client-...", client_id="key-id-...",
            ).to_secret_content()
            secret = self.app.add_secret(content)
            secret.grant(relation)
            self.creds.publish(
                relation,
                ProviderAppData(
                    secret_id=secret.id,
                    login_server="https://controlplane.example.com",
                    tags=["tag:child"],
                ),
            )

Requirer usage (tailscale-k8s / tailscale-beacon charm)::

    from canonical_service_mesh.interfaces.tailscale_credentials import (
        TailscaleCredentials,
        TailscaleCredentialsRequirer,
    )

    class MyBackendCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.creds = TailscaleCredentialsRequirer(self.model.relations, self.app)

        def _on_relation_changed(self, event):
            # A downstream charm has at most one tailscale-credentials relation.
            relation = self.model.get_relation("tailscale-credentials")
            if relation is None or not self.creds.is_ready(relation):
                return
            provider_data = self.creds.get_provider_data(relation)
            secret = self.model.get_secret(id=provider_data.secret_id)
            credentials = TailscaleCredentials.model_validate(secret.get_content())
            # tailscale up --auth-key=credentials.auth_key, etc.
            ...
"""

from ._tailscale_credentials import (
    DEFAULT_RELATION_NAME,
    ProviderAppData,
    TailscaleCredentials,
    TailscaleCredentialsProvider,
    TailscaleCredentialsRequirer,
)

__all__ = [
    "DEFAULT_RELATION_NAME",
    "ProviderAppData",
    "TailscaleCredentials",
    "TailscaleCredentialsProvider",
    "TailscaleCredentialsRequirer",
]
