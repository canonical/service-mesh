# Add Juju Applications and Models to the Service Mesh

Charmed Service Mesh makes it easy to add Juju applications, or even whole models, to your service mesh.  All Charmed service mesh products include a beacon charm (for example, [istio-beacon-k8s](https://charmhub.io/istio-beacon-k8s/)) which provides a few ways to put your application on the mesh.

For applications that have [added mesh support by implementing the `service-mesh` relation](../how-to/add-mesh-support-to-your-charm.md), relate them to the a beacon charm in the same model.  This will subscribe the charm to the mesh

For applications that have not implemented the `service-mesh` relation, beacon charms also provide a [`model-on-mesh`](https://charmhub.io/istio-beacon-k8s/configurations#model-on-mesh) feature.  If `model-on-mesh` is `True`, the beacon puts the entire model it is deployed to on the mesh, including all charmed applications deployed to that model and any Kubernetes workloads deployed in the Kubernetes namespace of that model.  Any application added to the mesh in this way will then use mTLS to communicate with other applications on the service mesh, as well as receive [hardening](../explanation/hardened-mode.md) if it is enabled.  

```{note}
While `model-on-mesh=True` may put everything on the mesh, its usually important to still relate any applications that implement the `service-mesh` relation to a beacon charm.  This is because the `service-mesh` relation is also used to automate [policy creation for access control](../explanation/authorization-policy-creation-in-istio.md).
```
