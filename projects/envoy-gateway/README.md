# Envoy Gateway under Istio Ambient

**TL;DR**: Envoy Gateway v1.6.3 works under Istio Ambient, provided the proxy pod is enrolled in the mesh and the required L4 AuthorizationPolicy is in place.

## Setup

### Requirements

- MicroK8s with addons: `metallb`, `dns`
- Juju 3.x bootstrapped on the MicroK8s cluster
- `just` command runner

> **Warning**: The setup and nuke recipes install and remove CRDs required by Envoy Gateway. Run on a fresh/dedicated cluster to avoid conflicts with existing workloads.

This will also most likely work with Canonical Kubernetes with the required [Cilium settings for Istio Ambient](https://canonical-service-mesh-documentation.readthedocs-hosted.com/latest/how-to/use-charmed-istio-with-canonical-kubernetes/), but MicroK8s was used here due to the author's lazy nature.

### What it sets up

1. A Juju model (`istio-test`) with Charmed Istio Ambient (istiod, ztunnel, CNI, waypoint proxy, ingress gateway)
2. Bookinfo sample apps (`productpage`, `details`) enrolled in the ambient mesh
3. Envoy Gateway v1.6.3 controller + GatewayClass (`eg`)
4. An Envoy Gateway + HTTPRoute routing `/productpage` to the bookinfo `productpage` service
5. The Envoy proxy pod enrolled in the ambient mesh
6. An L4 AuthorizationPolicy allowing the Envoy proxy to reach `productpage`

### Commands

To set up the environment, run:

```bash
# From the projects/envoy-gateway directory
# Setup everything
just -f justfiles/envoy-gateway.just istio-test-envoy-setup
# Tear down everything
just -f justfiles/envoy-gateway.just istio-test-envoy-nuke
```

Once setup completes, it prints the URLs for both gateways. To verify:

```bash
# Via Envoy Gateway
curl http://<envoy-gateway-ip>/productpage

# Via Istio Ingress
curl http://<istio-ingress-ip>/istio-test-productpage
```

Or open the URLs in a browser.

## How Envoy Gateway works under Istio Ambient

### The problem

When workloads are enrolled in Istio Ambient, the ztunnel enforces AuthorizationPolicies at the L4 level. The `istio-ingress-k8s` charm automatically creates a policy that only allows its own service account to reach the backend workloads.

A vanilla Envoy Gateway proxy, not enrolled in the mesh, has no SPIFFE identity. Its traffic arrives at the destination ztunnel as plaintext from an unknown source:

```
src.workload="envoy-istio-test-envoy-gateway-578b908d-b4d7677dd-6tqt4" src.namespace="envoy-gateway-system"
error="connection closed due to policy rejection: allow policies exist, but none allowed"
```

Even after enrolling in the mesh, the proxy gets a SPIFFE identity but still gets rejected because no policy explicitly allows its service account:

```
src.identity="spiffe://cluster.local/ns/envoy-gateway-system/sa/envoy-istio-test-envoy-gateway-578b908d"
error="connection closed due to policy rejection: allow policies exist, but none allowed"
```

### Making it work

Two things are needed for the Envoy Gateway to work under Istio Ambient:

#### 1. Enroll the proxy pod in the mesh

The Envoy proxy deployment needs the `istio.io/dataplane-mode: ambient` label so ztunnel captures its outbound traffic and assigns it a SPIFFE identity:

```bash
kubectl patch deployment -n istio-test <envoy-proxy-deployment> --type=merge \
    -p '{"spec":{"template":{"metadata":{"labels":{"istio.io/dataplane-mode":"ambient"}}}}}'
```

Once enrolled, the proxy's outbound traffic goes through ztunnel via HBONE, complying with ambient routing. The proxy gets a SPIFFE identity like:

```
spiffe://cluster.local/ns/istio-test/sa/<envoy-proxy-sa>
```

#### 2. Add an L4 AuthorizationPolicy

An explicit ALLOW policy is required so ztunnel permits the Envoy proxy's service account to reach the target workload:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: productpage-envoy-gateway-l4
  namespace: istio-test
spec:
  action: ALLOW
  selector:
    matchLabels:
      app.kubernetes.io/name: productpage
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/istio-test/sa/<envoy-proxy-sa>
    to:
    - operation:
        ports:
        - "9080"
```

This is an L4 policy. All paths are accessible through the envoy gateway. Ingress controllers resolve service endpoints directly (pod IPs), bypassing the service VIP. Because of this, ztunnel treats the traffic as pod-to-pod and does not route it through the waypoint - L7 waypoint policies have no effect on ingress traffic.

### Using with the Gateway API Integrator charm

The [`gateway-api-integrator`](https://github.com/canonical/gateway-api-integrator-operator) charm can use the Envoy Gateway controller to create Gateways and HTTPRoutes. Since the charm creates its own Gateway resource, the Envoy Gateway controller spins up a separate proxy Deployment for it. The same two steps (mesh enrollment + L4 policy) are required.

#### 1. Deploy the charm

Assuming the Envoy Gateway controller and GatewayClass (`eg`) are already installed (see setup above):

```bash
juju deploy self-signed-certificates ssc
juju deploy gateway-api-integrator gai --trust --config gateway-class=eg --config external-hostname=productpage.local
juju integrate gai:certificates ssc:certificates
juju integrate gai:gateway productpage:ingress
```

The GAI charm creates a Gateway with HTTP and HTTPS listeners (hostname-scoped to `productpage.local`), an HTTPRoute with path prefix `/istio-test-productpage` that rewrites to `/`, and a redirect from HTTP to HTTPS.

#### 2. Enroll the GAI proxy pod in the mesh

The controller creates a new proxy Deployment for the GAI Gateway. Find and enroll it:

```bash
DEPLOY=$(kubectl get deployment -n istio-test \
    -l gateway.envoyproxy.io/owning-gateway-name=gai \
    -o jsonpath='{.items[0].metadata.name}')
kubectl patch deployment -n istio-test "${DEPLOY}" --type=merge \
    -p '{"spec":{"template":{"metadata":{"labels":{"istio.io/dataplane-mode":"ambient"}}}}}'
```

#### 3. Add an L4 AuthorizationPolicy for the GAI proxy

```bash
SA=$(kubectl get deployment -n istio-test "${DEPLOY}" \
    -o jsonpath='{.spec.template.spec.serviceAccountName}')
kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: productpage-gai-l4
  namespace: istio-test
spec:
  action: ALLOW
  selector:
    matchLabels:
      app.kubernetes.io/name: productpage
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/istio-test/sa/${SA}
    to:
    - operation:
        ports:
        - "9080"
EOF
```

#### 4. Verify

The GAI Gateway sets up hostname-based routing with TLS termination, so `--resolve` is needed to set the correct SNI:

```bash
# HTTPS (path prefix is /istio-test-productpage, same as Istio ingress)
curl -k --resolve productpage.local:443:<gai-gateway-ip> \
    https://productpage.local/istio-test-productpage

# HTTP redirects to HTTPS
curl -H "Host: productpage.local" http://<gai-gateway-ip>/
```

### Notes

- **Policy management**: The `istio-ingress-k8s` charm self-manages its AuthorizationPolicy (it automatically creates the required policy for its own service account). For a vanilla Envoy Gateway, the policy must be created explicitly. If an Envoy Gateway charm were to exist, this could potentially be handled via the `service-mesh` relation.
- **Other ingress controllers**: This approach works with other ingress controllers (Traefik, Gateway API Integrator, etc.) - enroll the proxy in the mesh and add the L4 policy. Tested with both and confirmed the same waypoint bypass behavior.
- **Service mesh library limitations**: The current `service_mesh` library (`ServiceMeshConsumer`) cannot automate mesh enrollment for Gateway API controllers. The library's `reconcile_charm_labels()` patches the charm's own StatefulSet and Service by app name - but the proxy pod is a Deployment dynamically created by the Gateway API controller (e.g. Envoy Gateway), with a generated name and its own service account. The charm has no ownership over it. If this could be solved (e.g. by having the charm discover and patch the controller-created proxy Deployment), the solution would be generic across all Gateway API implementations - any controller (Envoy Gateway, Traefik, nginx, etc.) could be used with the `gateway-api-integrator` charm, and mesh enrollment + policy creation would be automated via the `service-mesh` relation.
