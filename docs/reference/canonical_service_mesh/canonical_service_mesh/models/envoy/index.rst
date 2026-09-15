canonical_service_mesh.models.envoy
===================================

.. py:module:: canonical_service_mesh.models.envoy

.. autoapi-nested-parse::

   Envoy Gateway resource models.



Classes
-------

.. autoapisummary::

   canonical_service_mesh.models.envoy.BackendEndpoint
   canonical_service_mesh.models.envoy.BackendObjectRef
   canonical_service_mesh.models.envoy.BackendSpec
   canonical_service_mesh.models.envoy.EnvoyProxySpec
   canonical_service_mesh.models.envoy.ExtAuth
   canonical_service_mesh.models.envoy.ExtAuthHTTPService
   canonical_service_mesh.models.envoy.FQDNEndpoint
   canonical_service_mesh.models.envoy.JSONPatchOperation
   canonical_service_mesh.models.envoy.LocalPolicyTargetRef
   canonical_service_mesh.models.envoy.MetricSink
   canonical_service_mesh.models.envoy.MetricsConfig
   canonical_service_mesh.models.envoy.OpenTelemetrySink
   canonical_service_mesh.models.envoy.ProxyBootstrap
   canonical_service_mesh.models.envoy.SecurityPolicySpec
   canonical_service_mesh.models.envoy.TelemetryConfig


Package Contents
----------------

.. py:class:: BackendEndpoint

   Bases: :py:obj:`pydantic.BaseModel`


   A single endpoint in an Envoy Gateway Backend resource.


   .. py:attribute:: fqdn
      :type:  Optional[FQDNEndpoint]
      :value: None



.. py:class:: BackendObjectRef

   Bases: :py:obj:`pydantic.BaseModel`


   A typed backend reference pointing at a specific group/kind resource.


   .. py:attribute:: group
      :type:  str


   .. py:attribute:: kind
      :type:  str


   .. py:attribute:: name
      :type:  str


   .. py:attribute:: namespace
      :type:  Optional[str]
      :value: None



.. py:class:: BackendSpec

   Bases: :py:obj:`pydantic.BaseModel`


   Spec of an Envoy Gateway Backend resource.


   .. py:attribute:: endpoints
      :type:  List[BackendEndpoint]


.. py:class:: EnvoyProxySpec

   Bases: :py:obj:`pydantic.BaseModel`


   Spec of a default EnvoyProxy resource.

   Carries an optional Envoy bootstrap override (e.g. to inject fixed
   Juju-topology stats tags via a JSON patch) and an optional OpenTelemetry
   metrics sink.


   .. py:attribute:: bootstrap
      :type:  Optional[ProxyBootstrap]
      :value: None



   .. py:attribute:: telemetry
      :type:  Optional[canonical_service_mesh.models.envoy._telemetry.TelemetryConfig]
      :value: None



.. py:class:: ExtAuth

   Bases: :py:obj:`pydantic.BaseModel`


   External authentication configuration for a SecurityPolicy.


   .. py:attribute:: http
      :type:  Optional[ExtAuthHTTPService]
      :value: None



.. py:class:: ExtAuthHTTPService

   Bases: :py:obj:`pydantic.BaseModel`


   HTTP-based ext auth service configuration.


   .. py:attribute:: backendRefs
      :type:  List[BackendObjectRef]


   .. py:attribute:: path
      :type:  Optional[str]
      :value: None



.. py:class:: FQDNEndpoint

   Bases: :py:obj:`pydantic.BaseModel`


   An FQDN-based endpoint for an Envoy Gateway Backend resource.


   .. py:attribute:: hostname
      :type:  str


   .. py:attribute:: port
      :type:  int


.. py:class:: JSONPatchOperation

   Bases: :py:obj:`pydantic.BaseModel`


   An RFC 6902 JSON Patch operation applied to the Envoy bootstrap.


   .. py:attribute:: op
      :type:  str


   .. py:attribute:: path
      :type:  str


   .. py:attribute:: value
      :type:  Optional[Any]
      :value: None



.. py:class:: LocalPolicyTargetRef

   Bases: :py:obj:`pydantic.BaseModel`


   A local (same-namespace) reference to a policy target resource.


   .. py:attribute:: group
      :type:  str


   .. py:attribute:: kind
      :type:  str


   .. py:attribute:: name
      :type:  str


.. py:class:: MetricSink

   Bases: :py:obj:`pydantic.BaseModel`


   A single Envoy Gateway metrics sink entry.


   .. py:attribute:: openTelemetry
      :type:  OpenTelemetrySink


   .. py:attribute:: type
      :type:  str
      :value: 'OpenTelemetry'



.. py:class:: MetricsConfig

   Bases: :py:obj:`pydantic.BaseModel`


   Envoy metrics configuration carrying one or more sinks.


   .. py:attribute:: sinks
      :type:  List[MetricSink]


.. py:class:: OpenTelemetrySink

   Bases: :py:obj:`pydantic.BaseModel`


   An OpenTelemetry metrics sink target (host + port).

   Matches the Envoy Gateway ``openTelemetry`` metric sink schema used by both
   ``EnvoyGateway.telemetry`` (control plane) and ``EnvoyProxy.spec.telemetry``
   (data plane).


   .. py:attribute:: host
      :type:  str


   .. py:attribute:: port
      :type:  int


.. py:class:: ProxyBootstrap

   Bases: :py:obj:`pydantic.BaseModel`


   Override or patch the Envoy bootstrap of the managed proxy fleet.

   Mirrors Envoy Gateway's ``ProxyBootstrap``: ``type`` selects the override
   strategy (``Replace``, ``Merge``, or ``JSONPatch``); ``value`` is a full
   bootstrap YAML string (for ``Replace``/``Merge``); ``jsonPatches`` is a list
   of RFC 6902 operations applied to the default bootstrap (for ``JSONPatch``).


   .. py:attribute:: jsonPatches
      :type:  Optional[List[JSONPatchOperation]]
      :value: None



   .. py:attribute:: type
      :type:  Optional[str]
      :value: None



   .. py:attribute:: value
      :type:  Optional[str]
      :value: None



.. py:class:: SecurityPolicySpec

   Bases: :py:obj:`pydantic.BaseModel`


   Spec of an Envoy Gateway SecurityPolicy resource.


   .. py:attribute:: extAuth
      :type:  Optional[ExtAuth]
      :value: None



   .. py:attribute:: targetRef
      :type:  LocalPolicyTargetRef


.. py:class:: TelemetryConfig

   Bases: :py:obj:`pydantic.BaseModel`


   Envoy telemetry configuration.


   .. py:attribute:: metrics
      :type:  Optional[MetricsConfig]
      :value: None



