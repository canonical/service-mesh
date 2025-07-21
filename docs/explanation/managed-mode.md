# Managed Mode

All Charmed Service Mesh Beacon charms (for example, [istio-beacon-k8s](https://charmhub.io/istio-beacon-k8s/)) include optional [management of authorization policies between applications](./authorization-policy-creation-in-istio.md).  When enabled, the beacon charms will automatically generate policies that allow related applications to communicate with each other [as specified by the charm authors via the `ServiceMeshConsumer` library](../how-to/add-mesh-support-to-your-charm.md).  

If managed mode is disabled, policy creation is left up to the administrator to do manually.
