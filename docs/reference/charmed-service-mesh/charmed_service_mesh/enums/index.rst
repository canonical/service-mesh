charmed_service_mesh.enums
==========================

.. py:module:: charmed_service_mesh.enums

.. autoapi-nested-parse::

   Shared enumerations for Charmed Service Mesh.



Classes
-------

.. autoapisummary::

   charmed_service_mesh.enums.Action
   charmed_service_mesh.enums.MeshType
   charmed_service_mesh.enums.Method
   charmed_service_mesh.enums.PolicyTargetType


Module Contents
---------------

.. py:class:: Action

   Bases: :py:obj:`str`, :py:obj:`enum.Enum`


   Action to take when an authorization policy rule matches.

   Initialize self.  See help(type(self)) for accurate signature.


   .. py:attribute:: allow
      :value: 'ALLOW'



   .. py:attribute:: custom
      :value: 'CUSTOM'



   .. py:attribute:: deny
      :value: 'DENY'



.. py:class:: MeshType

   Bases: :py:obj:`str`, :py:obj:`enum.Enum`


   Supported service mesh types.

   Initialize self.  See help(type(self)) for accurate signature.


   .. py:attribute:: istio
      :value: 'istio'



.. py:class:: Method

   Bases: :py:obj:`str`, :py:obj:`enum.Enum`


   HTTP method.

   Initialize self.  See help(type(self)) for accurate signature.


   .. py:attribute:: connect
      :value: 'CONNECT'



   .. py:attribute:: delete
      :value: 'DELETE'



   .. py:attribute:: get
      :value: 'GET'



   .. py:attribute:: head
      :value: 'HEAD'



   .. py:attribute:: options
      :value: 'OPTIONS'



   .. py:attribute:: patch
      :value: 'PATCH'



   .. py:attribute:: post
      :value: 'POST'



   .. py:attribute:: put
      :value: 'PUT'



   .. py:attribute:: trace
      :value: 'TRACE'



.. py:class:: PolicyTargetType

   Bases: :py:obj:`str`, :py:obj:`enum.Enum`


   Target type for policy classes.

   Initialize self.  See help(type(self)) for accurate signature.


   .. py:attribute:: app
      :value: 'app'



   .. py:attribute:: unit
      :value: 'unit'



