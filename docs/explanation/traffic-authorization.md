# Traffic Authorization

Traffic authorization is an important security feature in a Kubernetes cluster.  As Kubernetes enables multi-tenant deployments, microservice applications, and other complex patterns, it is important that:

* the applications that should talk to each other, can
* everything else, cannot

Authorization controls like this help prevent unwanted access within your network and limit the consequences if there's ever an intrusion in your network.  Some conceptual examples of authorization are:

* the `productpage` application can `GET` the `details` application at a specific path, like in [this tutorial](../tutorial/get-started-with-the-charmed-istio-mesh.md)
* the `prometheus` application can `GET` the `/metrics` endpoint of all units of an application

These are codified in concrete policies that differ between each service mesh.

## Authorization Management in a Charmed Service Mesh

Authorization management in a charmed service mesh centers around the Beacon charm.  Each charmed service mesh implements a Beacon charm that manages the service mesh for a model.  That charm:

* configures the model for use with the service mesh
* adds applications to the mesh
* creates authorization policies for service-to-service communication within the mesh

This is facilitated through the [`service-mesh` library](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) library, which is used to [Add Mesh Support to your Charm](../how-to/add-mesh-support-to-your-charm.md).  

By default, charmed service meshes are [hardened](../explanation/hardened-mode.md), in that they:

* establish mTLS communication between services on the mesh
* block service-to-service communication on the mesh unless a policy says otherwise

The Beacon charm is then responsible for creating the service-mesh specific objects (such as Istio `AuthorizationPolicies`) to implement the policy management.

Using the [Get started with the charmed Istio service mesh](../tutorial/get-started-with-the-charmed-istio-mesh.md) tutorial as an example, we see the `bookinfo-details-k8s` application provides a `details` integration that is required by the `bookinfo-productpage-k8s` to connect to the details page.  The `bookinfo-details-k8s` has also [added mesh support](../how-to/add-mesh-support-to-your-charm.md) in its [charm code](https://github.com/adhityaravi/bookinfo-operators/blob/14dd56ba0297d33f9accfa28b6615ffaaf8f4e8a/charms/bookinfo-details-k8s/src/charm.py#L38-L52) and defined a policy:

```python
class DetailsK8sCharm(CharmBase):
    """Charm for the Details microservice."""

    _stored = StoredState()

    def __init__(self, *args):
        # ... (truncated)

        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                AppPolicy(
                    relation="details",
                    endpoints=[
                        Endpoint(
                            ports=[PORT],
                            methods=[Method.get],
                            paths=["/health", "/details/*"]
                        )
                    ]
                )
            ]
        )
```

This means that, when related to a Beacon charm via the `service_mesh` relation, `bookinfo-details-k8s` will request traffic authorization for every application related to its `details` integration.  Specifically, it will request that those related applications can `GET` the `/health` and `/details/*` endpoints on a given port.  It is then the responsibility of the related beacon charm to create the policies necessary for this communication in the given service mesh.

```{note}
By default peer units of the charm are not allowed to access each other. This behavior can be changed if required. Check this [How-to](../how-to/add-mesh-support-to-your-charm.md) guide for more details. 
```

## Authorization Management in Charmed Istio

Istio's [Authorization](https://istio.io/latest/docs/concepts/security/#authorization) model centers around the [`AuthorizationPolicy`](https://istio.io/latest/docs/reference/config/security/authorization-policy/).  This object is how service-to-service communication is opened in an Istio service mesh.  The [istio-beacon-k8s](https://charmhub.io/istio-beacon-k8s) charm manages `AuthorizationPolicies` for Charmed Istio.  It automatically creates policies for charms related to it via the [`service_mesh`](https://charmhub.io/istio-beacon-k8s/integrations) interface.  

Using the above example of `bookinfo-details-k8s` requesting a policy for applications integrated in its `details` integration, if `bookinfo-details-k8s` is related to `istio-beacon-k8s` then we'd see the following `AuthorizationPolicy` created:

```yaml
# see this yaml yourself by using:
# kubectl get authorizationpolicy -n bookinfo istio-beacon-k8s-bookinfo-policy-bookinfo-productpage-k8s-bookinfo-bookinfo-details-k8s-HASH -o yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: istio-beacon-k8s-bookinfo-policy-bookinfo-productpage-k8s-bookinfo-bookinfo-details-k8s-2040d51a
  namespace: bookinfo
spec:
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/bookinfo/sa/bookinfo-productpage-k8s  # Allow communication from productpage app
    to:
    - operation:  # Only GET to these paths/ports
        methods:
        - GET
        paths:
        - /health
        - /details/*
        ports:
        - "9080"
  targetRefs:
  - group: ""
    kind: Service
    name: bookinfo-details-k8s  # Allow communication to the details app
```
