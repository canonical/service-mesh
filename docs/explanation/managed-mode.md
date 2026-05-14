# Managed Mode

Managed mode refers to a set of configuration options that together control how authorization policies are automatically created and enforced on the mesh.  When fully enabled, the beacon charm automatically generates `AuthorizationPolicies` based on what charm authors define via the [`ServiceMeshConsumer` library](../how-to/add-mesh-support-to-your-charm.md), so administrators do not need to create policies manually.

## manage-authorization-policies

The [`manage-authorization-policies`](https://charmhub.io/istio-beacon-k8s/configure#manage-authorization-policies) option on the beacon charm is the core of managed mode.  When set to `true` (the default), the beacon charm reads the policies defined by each charm via the `ServiceMeshConsumer` library and creates the corresponding Istio `AuthorizationPolicies` automatically.

For example, using the [Get started with Charmed Istio ambient](../tutorial/get-started-with-the-charmed-istio-mesh.md) tutorial, the `bookinfo-details-k8s` charm defines a policy allowing `GET` requests to `/health` and `/details/*` on port `9080`.  When `bookinfo-productpage-k8s` is related to `bookinfo-details-k8s` and both are on the mesh, the beacon charm creates an `AuthorizationPolicy` like the following:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: istio-beacon-k8s-bookinfo-policy-bookinfo-productpage-k8s-bookinfo-bookinfo-details-k8s-ad9cfa91
  namespace: bookinfo
  labels:
    app.kubernetes.io/instance: istio-beacon-k8s-bookinfo
    kubernetes-resource-handler-scope: istio-authorization-policy
spec:
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/bookinfo/sa/bookinfo-productpage-k8s
    to:
    - operation:
        methods:
        - GET
        paths:
        - /health
        - /details/*
        ports:
        - '9080'
  targetRefs:
  - group: ''
    kind: Service
    name: bookinfo-details-k8s
```

This policy allows `bookinfo-productpage-k8s` (identified by its service account) to make `GET` requests to the specified paths and port on `bookinfo-details-k8s`, and nothing else.

When `manage-authorization-policies` is set to `false`, the beacon charm will not create any authorization policies but will still perform other functions like providing a waypoint.  In this case, policy creation is left to the administrator.

## Related configuration options

Managed mode works alongside two configuration options on the [`istio-k8s`](https://charmhub.io/istio-k8s) charm that affect how the automatically created policies behave:

### hardened-mode

When [hardened mode](./hardened-mode.md) is enabled, global allow-nothing policies ensure that all traffic is denied unless an explicit `ALLOW` policy exists.  Without hardened mode, the policies created by managed mode only restrict traffic to workloads that are explicitly targeted.  Workloads without any policy still accept all traffic.  Enabling both managed mode and hardened mode together provides full zero-trust enforcement: managed mode creates the allow rules, and hardened mode ensures everything else is denied.

### auto-allow-waypoint-policy

The [`auto-allow-waypoint-policy`](https://charmhub.io/istio-k8s/configure#auto-allow-waypoint-policy) option (enabled by default) tells Istio ambient to automatically create synthetic L4 authorization policies that allow waypoints to forward traffic to their workloads.  Without this, the policies created by managed mode would be evaluated at the waypoint but the traffic from the waypoint to the destination workload would be blocked at the ztunnel layer unless a separate L4 policy exists.  Keeping this option enabled means administrators only need to think about the application level policies that managed mode handles.

## Disabling managed mode

All of the policy related configuration options described above can be disabled.  When they are, Charmed Istio ambient hands off all authorization control to the administrator.  No policies are automatically created or enforced, and all traffic management must be done manually by creating and maintaining `AuthorizationPolicies` directly.
