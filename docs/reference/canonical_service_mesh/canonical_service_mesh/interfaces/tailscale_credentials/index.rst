canonical_service_mesh.interfaces.tailscale_credentials
=======================================================

.. py:module:: canonical_service_mesh.interfaces.tailscale_credentials

.. autoapi-nested-parse::

   Tailscale credentials interface library.

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



Attributes
----------

.. autoapisummary::

   canonical_service_mesh.interfaces.tailscale_credentials.DEFAULT_RELATION_NAME


Classes
-------

.. autoapisummary::

   canonical_service_mesh.interfaces.tailscale_credentials.ProviderAppData
   canonical_service_mesh.interfaces.tailscale_credentials.TailscaleCredentials
   canonical_service_mesh.interfaces.tailscale_credentials.TailscaleCredentialsProvider
   canonical_service_mesh.interfaces.tailscale_credentials.TailscaleCredentialsRequirer


Package Contents
----------------

.. py:class:: ProviderAppData

   Bases: :py:obj:`pydantic.BaseModel`


   Non-secret provider app databag for the ``tailscale-credentials`` relation.

   Published by the provider to the requirer. The sensitive credential itself
   travels as a Juju charm secret; only its URI (``secret_id``) is carried here.


   .. py:method:: is_ready_for_use() -> bool

      Check whether this data represents a usable credential.

      :returns: True if both ``secret_id`` and ``login_server`` are set.



   .. py:method:: to_databag() -> dict[str, str]

      Serialize to a flat ``dict[str, str]`` for the relation databag.

      :returns: A flat ``dict[str, str]`` with wire-encoded values, ready to write
                to the provider app databag.



   .. py:attribute:: login_server
      :type:  str | None


   .. py:attribute:: secret_id
      :type:  str | None


   .. py:attribute:: tags
      :type:  list[str] | None


.. py:class:: TailscaleCredentials

   Bases: :py:obj:`pydantic.BaseModel`


   Credential secret content for the Tailscale backend.


   .. py:method:: to_secret_content() -> dict[str, str]

      Serialize to a flat ``dict[str, str]`` for a Juju secret's content.

      :returns: A flat ``dict[str, str]`` suitable for the charm's ``add_secret``.



   .. py:attribute:: auth_key
      :type:  str


   .. py:attribute:: client_id
      :type:  str


   .. py:attribute:: model_config


.. py:class:: TailscaleCredentialsProvider(relation_mapping: ops.RelationMapping, app: ops.Application, relation_name: str = DEFAULT_RELATION_NAME)

   Provider side wrapper for the ``tailscale-credentials`` relation.

   The provider publishes the non-secret app databag (secret URI, login-server,
   tags). The charm owns the secret lifecycle, the peer map, and control-plane
   minting; it builds the secret content via
   :meth:`TailscaleCredentials.to_secret_content`.

   Initialize the TailscaleCredentialsProvider.

   :param relation_mapping: The charm's RelationMapping (typically self.model.relations).
   :param app: This application (the tailscale-config charm).
   :param relation_name: The name of the relation.


   .. py:method:: publish(relation: ops.Relation, data: ProviderAppData) -> None

      Publish the provider app data to a specific relation.

      :param relation: A specific relation instance.
      :param data: The provider app data to publish. ``login_server`` must be non-empty.



   .. py:property:: relations
      :type: list[ops.Relation]


      Return the relation instances for the monitored relation.


.. py:class:: TailscaleCredentialsRequirer(relation_mapping: ops.RelationMapping, app: ops.Application, relation_name: str = DEFAULT_RELATION_NAME)

   Requirer side wrapper for the ``tailscale-credentials`` relation.

   The requirer reads the non-secret provider data (secret URI, login-server,
   tags) via :meth:`get_provider_data`; the charm then fetches the secret
   content with ``get_secret`` and validates it with
   ``TailscaleCredentials.model_validate``. The requirer never supplies data on
   the wire.

   Initialize the TailscaleCredentialsRequirer.

   :param relation_mapping: The charm's RelationMapping (typically self.model.relations).
   :param app: This application.
   :param relation_name: The name of the relation.


   .. py:method:: get_provider_data(relation: ops.Relation) -> ProviderAppData | None

      Read and validate the provider's non-secret app data for the relation.

      :param relation: A specific relation instance.

      :returns: A :class:`ProviderAppData` (secret URI + login-server + tags) if
                available and valid, else ``None``.



   .. py:method:: is_ready(relation: ops.Relation) -> bool

      Check whether the provider has published a usable credential.

      :param relation: A specific relation instance.

      :returns: True if provider data is present with both ``secret_id`` and
                ``login_server`` set.



   .. py:property:: relations
      :type: list[ops.Relation]


      Return the relation instances for the monitored relation.


.. py:data:: DEFAULT_RELATION_NAME
   :value: 'tailscale-credentials'


