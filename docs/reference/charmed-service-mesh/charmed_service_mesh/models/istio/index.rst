charmed_service_mesh.models.istio
=================================

.. py:module:: charmed_service_mesh.models.istio

.. autoapi-nested-parse::

   Istio-specific models.



Classes
-------

.. autoapisummary::

   charmed_service_mesh.models.istio.AuthorizationPolicySpec
   charmed_service_mesh.models.istio.ClaimToHeader
   charmed_service_mesh.models.istio.Condition
   charmed_service_mesh.models.istio.From
   charmed_service_mesh.models.istio.FromHeader
   charmed_service_mesh.models.istio.JWTRule
   charmed_service_mesh.models.istio.Operation
   charmed_service_mesh.models.istio.PolicyTargetReference
   charmed_service_mesh.models.istio.Provider
   charmed_service_mesh.models.istio.RequestAuthenticationSpec
   charmed_service_mesh.models.istio.Rule
   charmed_service_mesh.models.istio.Source
   charmed_service_mesh.models.istio.To
   charmed_service_mesh.models.istio.WorkloadSelector


Package Contents
----------------

.. py:class:: AuthorizationPolicySpec

   Bases: :py:obj:`pydantic.BaseModel`


   AuthorizationPolicySpec defines the structure of an Istio AuthorizationPolicy Kubernetes resource.


   .. py:method:: validate_provider_action()

      Validate that CUSTOM action must be set when specifying extension providers.



   .. py:method:: validate_target()

      Validate that at most one of targetRefs and selector is defined.



   .. py:attribute:: action
      :type:  charmed_service_mesh.enums.Action


   .. py:attribute:: provider
      :type:  Optional[Provider]


   .. py:attribute:: rules
      :type:  Optional[List[Rule]]
      :value: None



   .. py:attribute:: selector
      :type:  Optional[WorkloadSelector]


   .. py:attribute:: targetRefs
      :type:  Optional[List[PolicyTargetReference]]


.. py:class:: ClaimToHeader

   Bases: :py:obj:`pydantic.BaseModel`


   ClaimToHeader maps a JWT claim to a request header.


   .. py:attribute:: claim
      :type:  str


   .. py:attribute:: header
      :type:  str


.. py:class:: Condition

   Bases: :py:obj:`pydantic.BaseModel`


   Condition defines the condition for the rule.


   .. py:attribute:: key
      :type:  str


   .. py:attribute:: notValues
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: values
      :type:  Optional[List[str]]
      :value: None



.. py:class:: From

   Bases: :py:obj:`pydantic.BaseModel`


   From defines the source of the policy.


   .. py:attribute:: source
      :type:  Source


.. py:class:: FromHeader

   Bases: :py:obj:`pydantic.BaseModel`


   FromHeader specifies a header location from which to extract a JWT.


   .. py:attribute:: name
      :type:  str


   .. py:attribute:: prefix
      :type:  Optional[str]
      :value: None



.. py:class:: JWTRule

   Bases: :py:obj:`pydantic.BaseModel`


   JWTRule defines a JWT validation rule for RequestAuthentication.


   .. py:attribute:: audiences
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: forwardOriginalToken
      :type:  Optional[bool]
      :value: None



   .. py:attribute:: fromHeaders
      :type:  Optional[List[FromHeader]]
      :value: None



   .. py:attribute:: issuer
      :type:  str


   .. py:attribute:: jwksUri
      :type:  Optional[str]
      :value: None



   .. py:attribute:: outputClaimToHeaders
      :type:  Optional[List[ClaimToHeader]]
      :value: None



.. py:class:: Operation

   Bases: :py:obj:`pydantic.BaseModel`


   Operation defines the operation of the To model.


   .. py:attribute:: hosts
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: methods
      :type:  Optional[List[charmed_service_mesh.enums.Method]]
      :value: None



   .. py:attribute:: notHosts
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: notMethods
      :type:  Optional[List[charmed_service_mesh.enums.Method]]
      :value: None



   .. py:attribute:: notPaths
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: paths
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: ports
      :type:  Optional[List[str]]
      :value: None



.. py:class:: PolicyTargetReference

   Bases: :py:obj:`pydantic.BaseModel`


   PolicyTargetReference defines the target of the policy for waypoint bound policies.


   .. py:attribute:: group
      :type:  str


   .. py:attribute:: kind
      :type:  str


   .. py:attribute:: name
      :type:  str


   .. py:attribute:: namespace
      :type:  Optional[str]
      :value: None



.. py:class:: Provider

   Bases: :py:obj:`pydantic.BaseModel`


   Provider defines the extension provider for the policy.


   .. py:attribute:: name
      :type:  Optional[str]
      :value: None



.. py:class:: RequestAuthenticationSpec

   Bases: :py:obj:`pydantic.BaseModel`


   RequestAuthenticationSpec defines the spec of an Istio RequestAuthentication resource.


   .. py:method:: validate_target()

      Validate that at most one of targetRefs and selector is defined.



   .. py:attribute:: jwtRules
      :type:  Optional[List[JWTRule]]
      :value: None



   .. py:attribute:: selector
      :type:  Optional[charmed_service_mesh.models.istio._policy.WorkloadSelector]


   .. py:attribute:: targetRefs
      :type:  Optional[List[charmed_service_mesh.models.istio._policy.PolicyTargetReference]]


.. py:class:: Rule

   Bases: :py:obj:`pydantic.BaseModel`


   Rule defines a policy rule.


   .. py:attribute:: from_
      :type:  Optional[List[From]]


   .. py:attribute:: model_config


   .. py:attribute:: to
      :type:  Optional[List[To]]
      :value: None



   .. py:attribute:: when
      :type:  Optional[List[Condition]]
      :value: None



.. py:class:: Source

   Bases: :py:obj:`pydantic.BaseModel`


   Source defines the source of the policy.


   .. py:attribute:: ipBlocks
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: namespaces
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: notIpBlocks
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: notPrincipals
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: notRequestPrincipals
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: principals
      :type:  Optional[List[str]]
      :value: None



   .. py:attribute:: requestPrincipals
      :type:  Optional[List[str]]
      :value: None



.. py:class:: To

   Bases: :py:obj:`pydantic.BaseModel`


   To defines the destination of the policy.


   .. py:attribute:: operation
      :type:  Optional[Operation]
      :value: None



.. py:class:: WorkloadSelector

   Bases: :py:obj:`pydantic.BaseModel`


   WorkloadSelector defines the target of the policy for ztunnel bound policies.


   .. py:attribute:: matchLabels
      :type:  Dict[str, str]


