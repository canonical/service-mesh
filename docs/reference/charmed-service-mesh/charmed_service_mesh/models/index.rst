charmed_service_mesh.models
===========================

.. py:module:: charmed_service_mesh.models

.. autoapi-nested-parse::

   Kubernetes resource models.



Submodules
----------

.. toctree::
   :maxdepth: 1

   /reference/charmed-service-mesh/charmed_service_mesh/models/istio/index


Classes
-------

.. autoapisummary::

   charmed_service_mesh.models.AllowedRoutes
   charmed_service_mesh.models.BackendRef
   charmed_service_mesh.models.GRPCMethodMatch
   charmed_service_mesh.models.GRPCRouteMatch
   charmed_service_mesh.models.GRPCRouteResource
   charmed_service_mesh.models.GRPCRouteResourceSpec
   charmed_service_mesh.models.GRPCRouteRule
   charmed_service_mesh.models.GatewayTLSConfig
   charmed_service_mesh.models.HTTPPathMatch
   charmed_service_mesh.models.HTTPRouteMatch
   charmed_service_mesh.models.HTTPRouteResource
   charmed_service_mesh.models.HTTPRouteResourceSpec
   charmed_service_mesh.models.HTTPRouteRule
   charmed_service_mesh.models.IstioGatewayResource
   charmed_service_mesh.models.IstioGatewaySpec
   charmed_service_mesh.models.Listener
   charmed_service_mesh.models.Metadata
   charmed_service_mesh.models.ParentRef
   charmed_service_mesh.models.SecretObjectReference


Package Contents
----------------

.. py:class:: AllowedRoutes

   Bases: :py:obj:`pydantic.BaseModel`


   AllowedRoutes defines namespaces from which traffic is allowed.


   .. py:attribute:: namespaces
      :type:  Dict[str, str]


.. py:class:: BackendRef

   Bases: :py:obj:`pydantic.BaseModel`


   BackendRef specifies the backend service reference that traffic will be routed to.


   .. py:attribute:: name
      :type:  str


   .. py:attribute:: namespace
      :type:  str


   .. py:attribute:: port
      :type:  int


.. py:class:: GRPCMethodMatch

   Bases: :py:obj:`pydantic.BaseModel`


   GRPCMethodMatch defines the gRPC method matching configuration.


   .. py:attribute:: method
      :type:  Optional[str]
      :value: None



   .. py:attribute:: service
      :type:  Optional[str]
      :value: None



.. py:class:: GRPCRouteMatch

   Bases: :py:obj:`pydantic.BaseModel`


   GRPCRouteMatch defines the matching configuration for gRPC routes.


   .. py:attribute:: method
      :type:  Optional[GRPCMethodMatch]
      :value: None



.. py:class:: GRPCRouteResource

   Bases: :py:obj:`pydantic.BaseModel`


   GRPCRouteResource defines the structure of a GRPCRoute Kubernetes resource.


   .. py:attribute:: metadata
      :type:  charmed_service_mesh.models._metadata.Metadata


   .. py:attribute:: spec
      :type:  GRPCRouteResourceSpec


.. py:class:: GRPCRouteResourceSpec

   Bases: :py:obj:`pydantic.BaseModel`


   GRPCRouteResourceSpec defines the specification of a GRPCRoute Kubernetes resource.


   .. py:attribute:: parentRefs
      :type:  List[ParentRef]


   .. py:attribute:: rules
      :type:  List[GRPCRouteRule]


.. py:class:: GRPCRouteRule

   Bases: :py:obj:`pydantic.BaseModel`


   GRPCRouteRule defines the routing rule configuration for gRPC routes.


   .. py:attribute:: backendRefs
      :type:  Optional[List[BackendRef]]
      :value: []



   .. py:attribute:: filters
      :type:  Optional[list]
      :value: []



   .. py:attribute:: matches
      :type:  Optional[List[GRPCRouteMatch]]
      :value: None



.. py:class:: GatewayTLSConfig

   Bases: :py:obj:`pydantic.BaseModel`


   GatewayTLSConfig defines the TLS configuration for a listener.


   .. py:attribute:: certificateRefs
      :type:  Optional[List[SecretObjectReference]]
      :value: None



.. py:class:: HTTPPathMatch

   Bases: :py:obj:`pydantic.BaseModel`


   HTTPPathMatch defines the type and value of path matching.


   .. py:attribute:: type
      :type:  str
      :value: 'PathPrefix'



   .. py:attribute:: value
      :type:  str


.. py:class:: HTTPRouteMatch

   Bases: :py:obj:`pydantic.BaseModel`


   HTTPRouteMatch defines the path matching configuration.


   .. py:attribute:: path
      :type:  HTTPPathMatch


.. py:class:: HTTPRouteResource

   Bases: :py:obj:`pydantic.BaseModel`


   HTTPRouteResource defines the structure of an HTTPRoute Kubernetes resource.


   .. py:attribute:: metadata
      :type:  charmed_service_mesh.models._metadata.Metadata


   .. py:attribute:: spec
      :type:  HTTPRouteResourceSpec


.. py:class:: HTTPRouteResourceSpec

   Bases: :py:obj:`pydantic.BaseModel`


   HTTPRouteResourceSpec defines the specification of an HTTPRoute Kubernetes resource.


   .. py:attribute:: parentRefs
      :type:  List[ParentRef]


   .. py:attribute:: rules
      :type:  List[HTTPRouteRule]


.. py:class:: HTTPRouteRule

   Bases: :py:obj:`pydantic.BaseModel`


   HTTPRouteRule defines the routing rule configuration.


   .. py:attribute:: backendRefs
      :type:  Optional[List[BackendRef]]
      :value: []



   .. py:attribute:: filters
      :type:  Optional[list]
      :value: []



   .. py:attribute:: matches
      :type:  List[HTTPRouteMatch]


.. py:class:: IstioGatewayResource

   Bases: :py:obj:`pydantic.BaseModel`


   GatewayResource defines the structure of a Gateway Kubernetes resource.


   .. py:attribute:: metadata
      :type:  charmed_service_mesh.models._metadata.Metadata


   .. py:attribute:: spec
      :type:  IstioGatewaySpec


.. py:class:: IstioGatewaySpec

   Bases: :py:obj:`pydantic.BaseModel`


   GatewaySpec defines the specification of a gateway.


   .. py:attribute:: gatewayClassName
      :type:  str


   .. py:attribute:: listeners
      :type:  List[Listener]


.. py:class:: Listener

   Bases: :py:obj:`pydantic.BaseModel`


   Listener defines a port and protocol configuration.


   .. py:attribute:: allowedRoutes
      :type:  AllowedRoutes


   .. py:attribute:: hostname
      :type:  Optional[str]
      :value: None



   .. py:attribute:: name
      :type:  str


   .. py:attribute:: port
      :type:  int


   .. py:attribute:: protocol
      :type:  str


   .. py:attribute:: tls
      :type:  Optional[GatewayTLSConfig]
      :value: None



.. py:class:: Metadata

   Bases: :py:obj:`pydantic.BaseModel`


   Global metadata schema for Kubernetes resources.


   .. py:attribute:: annotations
      :type:  Optional[Dict[str, str]]
      :value: None



   .. py:attribute:: labels
      :type:  Optional[Dict[str, str]]
      :value: None



   .. py:attribute:: name
      :type:  str


   .. py:attribute:: namespace
      :type:  str


.. py:class:: ParentRef

   Bases: :py:obj:`pydantic.BaseModel`


   ParentRef specifies the parent gateway resource for this route.


   .. py:attribute:: name
      :type:  str


   .. py:attribute:: namespace
      :type:  str


   .. py:attribute:: sectionName
      :type:  str


.. py:class:: SecretObjectReference

   Bases: :py:obj:`pydantic.BaseModel`


   SecretObjectReference defines a reference to a Kubernetes secret.


   .. py:attribute:: group
      :type:  Optional[str]
      :value: None



   .. py:attribute:: kind
      :type:  Optional[str]
      :value: None



   .. py:attribute:: name
      :type:  str


   .. py:attribute:: namespace
      :type:  Optional[str]
      :value: None



