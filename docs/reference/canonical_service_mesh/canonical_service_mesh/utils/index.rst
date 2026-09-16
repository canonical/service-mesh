canonical_service_mesh.utils
============================

.. py:module:: canonical_service_mesh.utils

.. autoapi-nested-parse::

   Helper utilities for Charmed Service Mesh.



Submodules
----------

.. toctree::
   :maxdepth: 1

   /reference/canonical_service_mesh/canonical_service_mesh/utils/istio/index


Functions
---------

.. autoapisummary::

   canonical_service_mesh.utils.charm_kubernetes_label
   canonical_service_mesh.utils.generate_telemetry_labels
   canonical_service_mesh.utils.get_peer_identity_for_juju_application
   canonical_service_mesh.utils.get_peer_identity_for_service_account


Package Contents
----------------

.. py:function:: charm_kubernetes_label(model_name: str, app_name: str, prefix: str = '', suffix: str = '', max_length: int = 63, separator: str = '.') -> str

   Generate a Kubernetes-compliant label value.

   Returns a label in the form ``{prefix}{model_name}{separator}{app_name}{suffix}``.
   If the label exceeds ``max_length`` characters, model_name and app_name are truncated
   and a hash is appended to ensure uniqueness.

   See https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#syntax-and-character-set

   :param model_name: The name of the model (must be at least 1 character).
   :param app_name: The name of the application (must be at least 1 character).
   :param prefix: An optional prefix to prepend.
   :param suffix: An optional suffix to append.
   :param max_length: The maximum length of the label string.
   :param separator: The separator between model_name and app_name.

   :returns: The generated label string, at most ``max_length`` characters long.

   :raises ValueError: If model_name or app_name is empty, or if the fixed portion is too long.


.. py:function:: generate_telemetry_labels(app_name: str, model_name: str) -> dict[str, str]

   Generate telemetry labels for the application.

   The label key includes model_name and app_name, truncated to fit within
   Kubernetes' 63-character limit while maintaining uniqueness via a hash.

   :param app_name: The application name.
   :param model_name: The model (namespace) name.

   :returns: A dictionary with a single telemetry label.


.. py:function:: get_peer_identity_for_juju_application(app_name: str, namespace: str) -> str

   Return a Juju application's peer identity.

   Format is defined by ``principals`` in the Istio AuthorizationPolicy Source reference.
   Relies on the Juju convention that each application gets a ServiceAccount of the same name.

   :param app_name: The name of the Juju application.
   :param namespace: The Kubernetes namespace of the application.

   :returns: The SPIFFE identity string for the application.


.. py:function:: get_peer_identity_for_service_account(service_account: str, namespace: str) -> str

   Return a ServiceAccount's peer identity.

   Format: ``cluster.local/ns/{namespace}/sa/{service_account}``

   :param service_account: The Kubernetes ServiceAccount name.
   :param namespace: The Kubernetes namespace.

   :returns: The SPIFFE identity string for the service account.


