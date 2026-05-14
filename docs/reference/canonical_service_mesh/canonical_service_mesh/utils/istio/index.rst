canonical_service_mesh.utils.istio
================================

.. py:module:: canonical_service_mesh.utils.istio

.. autoapi-nested-parse::

   Istio-specific utilities.



Attributes
----------

.. autoapisummary::

   canonical_service_mesh.utils.istio.POLICY_RESOURCE_TYPES
   canonical_service_mesh.utils.istio.label_configmap_name_template


Functions
---------

.. autoapisummary::

   canonical_service_mesh.utils.istio.build_policy_resources_istio
   canonical_service_mesh.utils.istio.reconcile_charm_labels


Package contents
----------------

.. py:function:: build_policy_resources_istio(app_name: str, model_name: str, policies: list) -> Union[canonical_service_mesh.k8s.types.LightkubeResourcesList, List[None]]

   Build the required authorization policy resources for Istio service mesh.


.. py:function:: reconcile_charm_labels(client: lightkube.Client, app_name: str, namespace: str, label_configmap_name: str, labels: Dict[str, str]) -> None

   Reconcile user-defined Kubernetes labels on a Charm's Kubernetes objects.

   Manages labels on the charm's Pods (via StatefulSet) and Service. Uses a ConfigMap
   to track previously set labels so removed labels can be cleaned up.

   Args:
       client: The lightkube Client to use for Kubernetes API calls.
       app_name: The name of the application to reconcile labels for.
       namespace: The namespace in which the application is running.
       label_configmap_name: The name of the ConfigMap that stores the labels.
       labels: Labels to set. Previously set labels omitted here will be removed.


.. py:data:: POLICY_RESOURCE_TYPES

.. py:data:: label_configmap_name_template
   :value: 'juju-service-mesh-{app_name}-labels'

