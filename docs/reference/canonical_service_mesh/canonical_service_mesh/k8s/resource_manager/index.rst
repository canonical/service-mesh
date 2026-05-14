canonical_service_mesh.k8s.resource_manager
=========================================

.. py:module:: canonical_service_mesh.k8s.resource_manager

.. autoapi-nested-parse::

   Kubernetes resource managers.



Exceptions
----------

.. autoapisummary::

   canonical_service_mesh.k8s.resource_manager.K8sApiError


Classes
-------

.. autoapisummary::

   canonical_service_mesh.k8s.resource_manager.FakeApiError
   canonical_service_mesh.k8s.resource_manager.KubernetesResourceManager
   canonical_service_mesh.k8s.resource_manager.PolicyResourceManager


Functions
---------

.. autoapisummary::

   canonical_service_mesh.k8s.resource_manager.apply_many
   canonical_service_mesh.k8s.resource_manager.create_charm_default_labels
   canonical_service_mesh.k8s.resource_manager.delete_many
   canonical_service_mesh.k8s.resource_manager.patch_many


Package contents
----------------

.. py:exception:: K8sApiError

   Bases: :py:obj:`Exception`


   Raised when a Kubernetes API call fails due to a transport-level error.

   Initialize self.  See help(type(self)) for accurate signature.


.. py:class:: FakeApiError(code=400)

   Bases: :py:obj:`lightkube.core.exceptions.ApiError`


   Used to simulate an ApiError during testing.


.. py:class:: KubernetesResourceManager(labels: Optional[dict], resource_types: canonical_service_mesh.k8s.types.LightkubeResourceTypesSet, lightkube_client: lightkube.Client, logger: Optional[logging.Logger] = None)

   Helper API to manage (create, update, delete) a manifest of Kubernetes resources.

   Initialise a KubernetesResourceManager.

   Args:
       labels: Label selector for all resources managed by this KRM.
       resource_types: Set of Lightkube Resource classes managed by this KRM.
       lightkube_client: Lightkube Client for all k8s operations.
       logger: Logger for log output.


   .. py:method:: apply(resources: canonical_service_mesh.k8s.types.LightkubeResourcesList, force: bool = True)

      Apply the provided Kubernetes resources using server-side apply.

      Args:
          resources: A list of Lightkube Resource objects to apply.
          force: Force apply requests.



   .. py:method:: delete(ignore_missing=True)

      Delete all resources managed by this KubernetesResourceManager.

      Args:
          ignore_missing: Avoid raising 404 errors on deletion.



   .. py:method:: get_deployed_resources() -> canonical_service_mesh.k8s.types.LightkubeResourcesList

      Return a list of all deployed resources matching the label selector.

      Returns:
          A list of Lightkube Resource objects.



   .. py:method:: patch(resources: canonical_service_mesh.k8s.types.LightkubeResourcesList, force: bool = True, patch_type: lightkube.types.PatchType = PatchType.APPLY)

      Patch the provided Kubernetes resources.

      Args:
          resources: A list of Lightkube Resource objects to patch.
          force: Force patch requests.
          patch_type: Type of patch to use.



   .. py:method:: reconcile(resources: canonical_service_mesh.k8s.types.LightkubeResourcesList, force=True, ignore_missing=True, patch_type: lightkube.types.PatchType = PatchType.APPLY)

      Reconcile the given resources, removing, updating, or creating objects as required.

      Args:
          resources: A list of Lightkube Resource objects to apply.
          force: Force patch over managed resources.
          ignore_missing: Avoid raising 404 errors on deletion.
          patch_type: Type of patch to use.



   .. py:attribute:: labels


   .. py:attribute:: lightkube_client


   .. py:attribute:: resource_types


.. py:class:: PolicyResourceManager(charm: ops.CharmBase, lightkube_client: lightkube.Client, labels: Optional[Dict] = None, logger: Optional[logging.Logger] = None)

   A mesh-agnostic policy resource manager that manages policy manifests in Kubernetes.

   Can be used by charms to create and manage their own policy resources for scenarios like
   using Canonical Service Mesh in a non-managed model, managing custom policies, or managing
   authorization policies between charms not related to the service mesh beacon.

   Args:
       charm: The charm instantiating this object.
       lightkube_client: Lightkube Client for all k8s operations.
       labels: Label selector for managed resources.
       logger: Logger for log output.


   .. py:method:: delete(ignore_missing=True)

      Delete all the policy resources handled by this manager.

      Args:
          ignore_missing: Avoid raising 404 errors on deletion.



   .. py:method:: reconcile(policies: list, mesh_type: canonical_service_mesh.enums.MeshType, raw_policies: Optional[List[canonical_service_mesh.k8s.types.istio.AuthorizationPolicy]] = None, force: bool = True, ignore_missing: bool = True) -> None

      Reconcile the given policies, removing, updating, or creating objects as required.

      Args:
          policies: A list of MeshPolicy objects defining the required policy behaviour.
          mesh_type: The type of service mesh.
          raw_policies: Pre-built policy resources to merge with the built policies.
          force: Force apply over managed resources.
          ignore_missing: Avoid raising 404 errors on deletion.

      Raises:
          TypeError: If raw_policies contains resources of unsupported types.



.. py:function:: apply_many(client: lightkube.Client, objs: Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]], field_manager: str = None, force: bool = False, logger: logging.Logger = None) -> Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]]

   Create or configure an iterable of Lightkube objects using client.apply().

   Resources are sorted before applying to avoid referencing objects before they are created.

   Args:
       client: Lightkube client to use for applying resources.
       objs: Iterable of objects to create.
       field_manager: Name associated with the actor making these changes.
       force: Force apply requests, re-acquiring conflicting fields.
       logger: Logger to use for applying resources.

   Returns:
       A list of Resource objects returned from client.apply().


.. py:function:: create_charm_default_labels(application_name: str, model_name: str, scope: str) -> dict

   Return a default label style for the KubernetesResourceHandler label selector.


.. py:function:: delete_many(client: lightkube.Client, objs: Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]], ignore_missing: bool = True, logger: logging.Logger = None) -> None

   Delete an iterable of objects using client.delete().

   Resources are deleted in reverse order to avoid deleting objects that are being used.

   Args:
       client: Lightkube Client to use for deletions.
       objs: Iterable of objects to delete.
       ignore_missing: Avoid raising 404 errors on deletion.
       logger: Logger to use for deleting resources.


.. py:function:: patch_many(client: lightkube.Client, objs: Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]], patch_type: lightkube.types.PatchType = PatchType.APPLY, field_manager: str = None, force: bool = False, logger: logging.Logger = None) -> Iterable[Union[GlobalResourceTypeVar, NamespacedResourceTypeVar]]

   Create or configure an iterable of Lightkube objects using client.patch().

   Similar to apply_many() but uses client.patch() with configurable patch_type.

   Args:
       client: Lightkube client to use for patching resources.
       objs: Iterable of objects to create.
       patch_type: Type of patch to use. Defaults to PatchType.APPLY.
       field_manager: Name associated with the actor making these changes.
       force: Force patch requests, re-acquiring conflicting fields.
       logger: Logger to use for patching resources.

   Returns:
       A list of Resource objects returned from client.patch().

