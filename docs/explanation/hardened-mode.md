# Hardened Mode

In a zero-trust network, no service is trusted by default and every request must be explicitly authorized before it is allowed through.  Hardened mode brings this principle to the service mesh by enforcing a deny-by-default security posture: all inbound traffic to services on the mesh is denied unless an authorization policy explicitly allows it.

## Why hardened mode is needed

By default, Istio ambient only enforces authorization on workloads that are explicitly targeted by an `AuthorizationPolicy`.  Any workload without a policy applied to it will accept all inbound traffic.  This means:

* if a service on the mesh has no policy targeting it, the **ztunnel** will allow any traffic through to that service
* when [`auto-allow-waypoint-policy`](https://charmhub.io/istio-k8s/configurations#auto-allow-waypoint-policy) is enabled (the default), if no policy targets a service at the **waypoint**, any service can reach it

In practice, this leaves services that haven't been explicitly locked down wide open.  Hardened mode closes this gap by ensuring that all traffic is denied by default across the entire mesh.

## How it works

Enabling hardened mode on the [`istio-k8s`](https://charmhub.io/istio-k8s) charm creates two global **allow-nothing** `AuthorizationPolicies`.

### Why allow-nothing instead of deny-all?

The distinction matters because of how Istio ambient [evaluates authorization policies](https://istio.io/latest/docs/concepts/security/#authorization-policy-precedence).  Istio ambient processes policies in this order: `CUSTOM` then `DENY` then `ALLOW`.  A `DENY` policy always takes precedence.  Once traffic matches a `DENY` rule, it is rejected regardless of any `ALLOW` policies.  This means a global `DENY`-all policy would lock down the cluster permanently with no way to override it.

An allow-nothing policy works differently.  It is an `ALLOW` policy with an empty rule set, meaning it matches no traffic.  However, its presence activates Istio ambient's [implicit deny behavior](https://istio.io/latest/docs/concepts/security/#allow-nothing-deny-all-and-allow-all-policy): once at least one `ALLOW` policy exists for a workload, any traffic that does not match an `ALLOW` rule is denied.  Other `ALLOW` policies can then selectively open up the specific traffic that should be permitted.  This gives us a secure default that can still be overridden by explicit allow rules.

### ztunnel allow-nothing policy

An `AuthorizationPolicy` with an empty spec acts as a global allow-nothing policy.  This ensures that any traffic not matched by an explicit `ALLOW` policy is denied at the ztunnel layer:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: istio-k8s-istio-system-policy-global-allow-nothing-ztunnel
  namespace: istio-system
spec: {}
```

### Waypoint allow-nothing policy

A similar policy targets the `istio-waypoint` `GatewayClass`, locking down all traffic that passes through the waypoint:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: istio-k8s-istio-system-policy-global-allow-nothing-waypoint
  namespace: istio-system
spec:
  targetRefs:
  - kind: GatewayClass
    group: gateway.networking.k8s.io
    name: istio-waypoint
```

Together, these two policies ensure that no service-to-service communication is allowed anywhere on the mesh unless an explicit `ALLOW` policy exists for it.  See [Traffic authorization](./traffic-authorization.md) for how these allow policies are created by the beacon charm.

## Effect on ingress traffic

Hardened mode also blocks external traffic from reaching the Istio ingress gateway, since the global deny applies to all inbound traffic including traffic arriving from a `LoadBalancer`.

To handle this, the [`istio-ingress-k8s`](https://charmhub.io/istio-ingress-k8s) charm automatically creates an `ALLOW` policy that permits external traffic to reach the gateway:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: istio-ingress-k8s-istio-system-external-traffic
  namespace: istio-system
spec:
  action: ALLOW
  targetRefs:
  - kind: Gateway
    group: gateway.networking.k8s.io
    name: istio-ingress-k8s
  rules:
  - from:
    - source:
        ipBlocks:
        - "0.0.0.0/0"
```

By default, this allows traffic from any source IP (`0.0.0.0/0`) because an ingressed application is typically meant to be publicly accessible.  To restrict access to specific source IPs or CIDR ranges, use the `external-traffic-policy-cidrs` configuration option on [`istio-ingress-k8s`](https://charmhub.io/istio-ingress-k8s/configurations).

## Enabling hardened mode

To enable hardened mode, set the `hardened-mode` configuration option on the `istio-k8s` charm:

```bash
juju config istio-k8s hardened-mode=true
```

For all available configuration options, see the [istio-k8s](https://charmhub.io/istio-k8s/configurations) and [istio-ingress-k8s](https://charmhub.io/istio-ingress-k8s/configurations) charm configuration pages.
