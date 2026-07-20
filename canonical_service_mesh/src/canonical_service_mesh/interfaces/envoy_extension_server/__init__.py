# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy extension-server interface library.

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
"""

from ._envoy_extension_server import (
    DEFAULT_EXTENSION_SERVER_PORT,
    DEFAULT_RELATION_NAME,
    ControllerIdentityData,
    ExtensionServerData,
    ExtensionServerProvider,
    ExtensionServerRequirer,
)

__all__ = [
    "DEFAULT_EXTENSION_SERVER_PORT",
    "DEFAULT_RELATION_NAME",
    "ControllerIdentityData",
    "ExtensionServerData",
    "ExtensionServerProvider",
    "ExtensionServerRequirer",
]
