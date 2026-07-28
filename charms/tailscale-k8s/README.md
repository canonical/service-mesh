# Tailscale K8s Charmed Operator

## Description

[Tailscale](https://tailscale.com) is a mesh VPN built on WireGuard that makes it easy to connect devices and services across networks. The Tailscale Kubernetes operator extends this to Kubernetes workloads by watching for `LoadBalancer` Services with `loadBalancerClass: tailscale` and automatically registering them on a tailnet.

The `tailscale-k8s` charm deploys and manages the upstream [Tailscale Kubernetes operator](https://tailscale.com/kb/1236/kubernetes-operator) via Juju. It handles credential injection, proxy lifecycle, and tailnet registration for workloads exposed through `tailscale-beacon-k8s`.

This charm supports both **Tailscale SaaS** and **Headscale** (>= v0.30.0)
control planes. See [Headscale](#headscale) for the version and TLS
requirements.

## Architecture

- **One `tailscale-k8s` per cluster.** The upstream operator runs as a single replica with a shared state Secret and does not support leader election. The charm enforces this.
- **Implicit coordination with beacons.** `tailscale-beacon-k8s` creates `LoadBalancer` Services; this operator detects them cluster-wide and handles tailnet registration. No direct relation between the two is needed.
- **Credentials via config (relation planned).** OAuth credentials are provided
  manually as a Juju secret today; automatic provisioning via a relation to
  `tailscale-config` is planned (see [relation mode](#provide-credentials-relation-mode)).

## Usage

### Deploy

```bash
juju add-model tailscale-system
juju deploy tailscale-k8s --trust
```

The charm will enter `blocked` status until credentials are provided.

### Provide credentials (manual mode)

Create an OAuth client in the Tailscale admin console at **Settings > OAuth clients > Generate OAuth client**. The client requires:

- **Tags:** Must carry `tag:k8s-operator` (or whatever you set `operator-tags` to)
- **Scopes:**
  - `devices:core` (read and write) — to register and manage the operator's own device
  - `auth_keys` — to mint auth keys for proxy pods

This gives you a **client ID** (e.g. `k123abc...`) and a **client secret** (e.g. `tskey-client-...`). Store both in a Juju secret:

```bash
juju add-secret tailscale-creds \
    client-id=<oauth-client-id> \
    client-secret=<oauth-client-secret>

juju grant-secret tailscale-creds tailscale-k8s

juju config tailscale-k8s credentials=secret:<secret-id>
```

| Secret field | Value |
|---|---|
| `client-id` | The OAuth client ID from the Tailscale admin console |
| `client-secret` | The OAuth client secret (starts with `tskey-client-`) |

### Provide credentials (relation mode)

> **Planned / not yet available.** The `tailscale-credentials` relation to
> `tailscale-config` is targeted for the initial release but is not implemented
> yet (the interface and charm library are still being finalized). Use manual
> mode above for now.

When `tailscale-config` is available, relate it to receive credentials automatically:

```bash
juju relate tailscale-k8s:tailscale-credentials tailscale-config:tailscale-credentials
```

If both manual credentials and the relation are present, the charm blocks until the conflict is resolved.

### Headscale

The charm works with a self-hosted [Headscale](https://headscale.net) control
plane, subject to two requirements:

- **Headscale >= v0.30.0.** The operator authenticates and mints proxy auth keys
  through Headscale's Tailscale-compatible v2 API with OAuth clients, which
  landed in Headscale v0.30.0 ([juanfont/headscale#3334](https://github.com/juanfont/headscale/pull/3334)).
  Earlier Headscale versions cannot drive the operator.
- **Plain HTTP, or TLS with a system/publicly-trusted certificate.** Tailscale
  clients require the control plane over HTTPS for their sustained connection,
  and the operator's proxy pods only trust their image's system CA store. A
  Headscale served with a **private/self-signed CA is not supported** for
  exposing workloads: a custom CA cannot be injected into the operator-managed
  proxy pods (the operator's ProxyClass has no volume/CA mechanism upstream).
  Use a publicly/ACME-trusted certificate — Tailscale bundles the Let's Encrypt
  roots, so LE-issued certs work out of the box — or plain HTTP.

Create an OAuth client on Headscale (`headscale oauth-clients create`) and
provide it exactly like a Tailscale OAuth client — `client-id` + `client-secret`
in a Juju secret (see [manual mode](#provide-credentials-manual-mode)) — then
point the charm at the Headscale URL:

```bash
juju config tailscale-k8s login-server=https://headscale.example.com
```

## Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `credentials` | secret | — | Juju secret containing `client-id` (OAuth client ID) and `client-secret` (OAuth client secret) |
| `login-server` | string | `""` | Control plane URL. Empty for Tailscale SaaS; set to a Headscale URL (>= v0.30.0; HTTP or a system/publicly-trusted TLS cert — see [Headscale](#headscale)) |
| `operator-tags` | string | `tag:k8s-operator` | Comma-separated tags for the operator device |
| `proxy-tags` | string | `tag:k8s` | Comma-separated tags for proxy pods |

### Tag model

The tailnet ACL `tagOwners` must grant:
- The credential carries `operator-tags` (the operator authenticates by exact match)
- `operator-tags` owns `proxy-tags` (the operator mints proxy auth keys via hierarchy)

Standard setup:
```json
{
  "tagOwners": {
    "tag:k8s-operator": [],
    "tag:k8s": ["tag:k8s-operator"]
  }
}
```

## Kubernetes resources created

The charm creates these resources directly (via the Kubernetes API, outside its
own Pod spec):

| Resource | Name | Scope | Purpose |
|----------|------|-------|---------|
| ServiceAccount | `proxies` | namespaced | Identity for proxy pods spawned by the operator |
| Role | `proxies` | namespaced | Proxy permissions: secrets CRUD, events |
| RoleBinding | `proxies` | namespaced | Binds the `proxies` SA to its Role |
| IngressClass | `tailscale` | cluster | Registers the `tailscale.com/ts-ingress` controller |

Cleanup on removal: the namespaced resources are labelled and garbage-collected
by Juju automatically. The cluster-scoped `IngressClass` is not (Juju's cleanup
is namespace-scoped), so the charm deletes it on removal and additionally sets
an `ownerReference` to the model Namespace, letting Kubernetes garbage-collect
it if the model is destroyed (including `--force`, which skips charm hooks).

CRDs (connectors, dnsconfigs, proxyclasses, proxygrouppolicies, proxygroups, recorders, tailnets) are installed by the charm from bundled manifests before the operator starts. They are intentionally **not** deleted on charm removal, to avoid cascading deletes of user-created ProxyGroups/Connectors.

## Teardown order (important)

The upstream operator adds a `tailscale.com/finalizer` to every
`loadBalancerClass: tailscale` Service it manages (i.e. every workload exposed
via `tailscale-beacon-k8s`). That finalizer is only cleared by the operator
itself, as it tears down the proxy for that Service.

**Always remove exposed workloads before removing `tailscale-k8s`.** If the
operator is removed while such Services still exist, nothing clears their
finalizers, so the Services — and therefore the model's namespace, and therefore
the model — get stuck deleting indefinitely.

Safe order:
1. Remove the apps / `tailscale-beacon-k8s` (or delete the
   `loadBalancerClass: tailscale` Services) **first**.
2. Wait until those Services are gone (the operator deletes the proxy and clears
   the finalizer).
3. Then remove `tailscale-k8s` / `destroy-model`.

Avoid `juju destroy-model --force` while such Services still exist — `--force`
skips the operator's reconcile, orphaning the finalizers. If a namespace is
already stuck for this reason, clear the finalizer manually:

```bash
kubectl patch svc <name> -n <model> --type=json \
    -p '[{"op":"remove","path":"/metadata/finalizers"}]'
```

## Relations

| Endpoint | Interface | Role | Description |
|----------|-----------|------|-------------|
| `tailscale-credentials` | `tailscale_credentials` | requirer | Receives OAuth credentials from `tailscale-config`. **Planned — not yet implemented.** |

## Development

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- [tox](https://tox.wiki/) (optional, wraps uv)
- [charmcraft](https://juju.is/docs/sdk/install-charmcraft) (for packing)

### Run tests

```bash
# All checks (lint + static + unit)
tox

# Unit tests only
tox -e unit

# Integration tests (requires a Juju K8s controller)
tox -e integration
```

### Build the charm

```bash
charmcraft pack
```
