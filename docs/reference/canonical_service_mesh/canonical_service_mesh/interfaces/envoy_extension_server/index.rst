canonical_service_mesh.interfaces.envoy_extension_server
========================================================

.. py:module:: canonical_service_mesh.interfaces.envoy_extension_server

.. autoapi-nested-parse::

   Envoy extension-server interface library.

   This library provides the provider and requirer sides of the
   ``envoy-extension-server`` relation interface, which wires an Envoy Gateway
   control plane to a server implementing Envoy Gateway's
   `Extension Server <https://gateway.envoyproxy.io/docs/tasks/extensibility/extension-server/>`_
   protocol.

   What is this library for?
   =========================

   The ``envoy-controller-k8s`` charm runs the Envoy Gateway control plane. Envoy
   Gateway can delegate fine-tuning of its generated xDS to an external gRPC
   *extension server* — today, the Envoy AI Gateway controller
   (``envoy-ai-gateway-k8s``). To use it, Envoy Gateway must be configured with the
   extension server's address (``extensionManager.service.fqdn`` + port ``1063``)
   and the relevant ``xdsTranslator`` hooks. The control plane cannot know that
   address until the two charms are related — hence this interface.

   The relation is the on/off switch for the extension: when present, the control
   plane wires ``extensionManager`` to the provider's address; when absent, it runs
   plain. The provider (extension server) advertises its gRPC endpoint; the
   requirer (control plane) publishes its ``controllerName`` and namespace back so
   the provider can gate itself to the correct GatewayClass.

   Provider usage (extension server, e.g. the AI Gateway controller)::

       from canonical_service_mesh.interfaces.envoy_extension_server import (
           ExtensionServerProvider,
       )

       class MyExtensionServerCharm(CharmBase):
           def __init__(self, framework):
               super().__init__(framework)
               self.ext_server = ExtensionServerProvider(self)

           def _publish(self):
               self.ext_server.publish_data(
                   extension_server_fqdn="my-ext-server.my-model.svc.cluster.local",
                   extension_server_port="1063",
               )

   Requirer usage (Envoy Gateway control plane)::

       from canonical_service_mesh.interfaces.envoy_extension_server import (
           ExtensionServerRequirer,
       )

       class MyControlPlaneCharm(CharmBase):
           def __init__(self, framework):
               super().__init__(framework)
               self.ext_server = ExtensionServerRequirer(self)

           def _reconcile(self):
               if self.ext_server.is_ready:
                   data = self.ext_server.get_extension_server_data()
                   # configure EG extensionManager with data.extension_server_fqdn/port
               self.ext_server.publish_controller_identity(
                   controller_name="envoy-controller-k8s",
                   namespace=self.model.name,
               )



Attributes
----------

.. autoapisummary::

   canonical_service_mesh.interfaces.envoy_extension_server.DEFAULT_EXTENSION_SERVER_PORT
   canonical_service_mesh.interfaces.envoy_extension_server.DEFAULT_RELATION_NAME


Classes
-------

.. autoapisummary::

   canonical_service_mesh.interfaces.envoy_extension_server.ControllerIdentityData
   canonical_service_mesh.interfaces.envoy_extension_server.ExtensionServerData
   canonical_service_mesh.interfaces.envoy_extension_server.ExtensionServerProvider
   canonical_service_mesh.interfaces.envoy_extension_server.ExtensionServerRequirer


Package Contents
----------------

.. py:class:: ControllerIdentityData

   Bases: :py:obj:`pydantic.BaseModel`


   Requirer-side databag model for the envoy-extension-server relation.

   Carries the Envoy Gateway control plane's identity so the provider can gate
   itself to the correct GatewayClass and namespace.


   .. py:attribute:: controller_name
      :type:  str | None


   .. py:attribute:: model_config


   .. py:attribute:: namespace
      :type:  str | None


.. py:class:: ExtensionServerData

   Bases: :py:obj:`pydantic.BaseModel`


   Provider-side databag model for the envoy-extension-server relation.

   Each field maps to a top-level key in the provider's application databag.
   Use ``ops.Relation.load`` / ``ops.Relation.save`` to (de)serialise.


   .. py:attribute:: extension_server_fqdn
      :type:  str | None


   .. py:attribute:: extension_server_port
      :type:  str | None


   .. py:attribute:: model_config


.. py:class:: ExtensionServerProvider(charm: ops.CharmBase, relation_name: str = DEFAULT_RELATION_NAME)

   Bases: :py:obj:`ops.framework.Object`


   Provider side of the envoy_extension_server interface.

   Used by the extension server (e.g. the AI Gateway controller) to advertise
   the address of its extension-server gRPC endpoint and to read the Envoy
   Gateway control plane's identity from the requirer.

   Initialize the ExtensionServerProvider.

   Args:
       charm: The charm that owns this provider.
       relation_name: Name of the relation (default: "envoy-extension-server").


   .. py:method:: get_controller_identity() -> ControllerIdentityData | None

      Read the Envoy Gateway control plane's identity from the requirer.

      Returns:
          The requirer's ControllerIdentityData if a single relation has
          published valid data, else None.



   .. py:method:: publish_data(extension_server_fqdn: str, extension_server_port: str = DEFAULT_EXTENSION_SERVER_PORT) -> None

      Publish the extension-server address to all related applications.

      Args:
          extension_server_fqdn: Cluster-internal FQDN of the extension-server gRPC service.
          extension_server_port: Port of the extension-server gRPC service.



.. py:class:: ExtensionServerRequirer(charm: ops.CharmBase, relation_name: str = DEFAULT_RELATION_NAME)

   Bases: :py:obj:`ops.framework.Object`


   Requirer side of the envoy_extension_server interface.

   Used by the Envoy Gateway control plane to read the extension-server address
   it must configure EG's ``extensionManager`` with, and to publish its own
   controller identity so the provider can gate itself.

   Initialize the ExtensionServerRequirer.

   Args:
       charm: The charm that owns this requirer.
       relation_name: Name of the relation (default: "envoy-extension-server").


   .. py:method:: get_extension_server_data() -> ExtensionServerData | None

      Read the provider's extension-server address.

      Only data with both ``extension_server_fqdn`` and
      ``extension_server_port`` present is treated as ready.

      Returns:
          The provider's ExtensionServerData if available and complete, else None.



   .. py:method:: publish_controller_identity(controller_name: str, namespace: str) -> None

      Publish this control plane's identity to all related applications.

      Args:
          controller_name: The EG controllerName / GatewayClass the extension targets.
          namespace: The namespace the EG control plane runs in.



   .. py:property:: is_ready
      :type: bool


      Whether the provider has published a usable extension-server address.

      Returns:
          True if the related provider has published both
          extension_server_fqdn and extension_server_port.



.. py:data:: DEFAULT_EXTENSION_SERVER_PORT
   :value: '1063'


.. py:data:: DEFAULT_RELATION_NAME
   :value: 'envoy-extension-server'


