# Add Juju Applications and Models to the Service Mesh

Charmed Service Mesh makes it easy to add Juju applications, of even whole models, to your service mesh.  All Charmed service mesh produces include a beacon charm (for example, [istio-beacon-k8s](https://charmhub.io/istio-beacon-k8s/)) which offer the following ways to integrate your applications with the mesh:

* if [`model-on-mesh`](https://charmhub.io/istio-beacon-k8s/configurations#model-on-mesh) mode is on, the beacon puts the entire model that it is deployed to on the mesh.  This includes all charmed applications deployed to that model, as well as any Kubernetes workloads that are deployed in the Kubernetes namespace of that model
* if an application relates to a beacon using the [`service-mesh` relation](https://charmhub.io/istio-beacon-k8s/integrations), that application puts itself on the mesh using the [`service_mesh`](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) library.

These two modes can coexist - there will be no configuration error if applications are related to a beacon via the `service-mesh` relation while beacon also has `model-on-mesh=` enabled.
