Service Mesh documentation
==========================

A service mesh is a dedicated infrastructure layer that manages service-to-service communication in microservice architectures. It provides capabilities like traffic management, security, and observability without requiring changes to application code. However, service meshes are complex systems that require significant time to learn and deep understanding to operate effectively.

The Canonical Service Mesh leverages application modeling fro [Juju](https://juju.is/) to simplify service mesh operations. By using charms and relations, complex configurations like creating authorization policies, on-boarding [Kubernetes](https://kubernetes.io/) applications onto the mesh, and managing traffic routing are automated, reducing operational overhead and the potential for misconfiguration. This approach makes service mesh technology more accessible while maintaining the full power of the underlying platform.

For Platform Engineers and DevOps teams, Canonical Service Mesh provides a turn-key, out-of-the-box solution for improved microservice communication, security, and observability.

.. note::
   Currently, Canonical Service Mesh offers Charmed Istio in ambient mode

.. toctree::
   :hidden:
   :maxdepth: 2

   Tutorials </tutorial/index>
   How-to guides </how-to/index>
   Explanation </explanation/index>
   Reference </reference/index>

In this documentation
---------------------

.. grid:: 1 1 2 2

   .. grid-item-card:: Tutorial
      :link: /tutorial/index
      :link-type: doc

      **Get started** - a hands-on introduction the Canonical Service Mesh.

   .. grid-item-card:: How-to guides
      :link: /how-to/index
      :link-type: doc

      **Step-by-step guides** - learn key operations and customization.

.. grid:: 1 1 2 2


   .. grid-item-card:: Explanation
      :link: /explanation/index
      :link-type: doc

      **Discussion and clarification** of key topics and concepts

   .. grid-item-card:: Reference
      :link: /reference/index
      :link-type: doc

      **Technical information** - specifications, APIs, architecture
