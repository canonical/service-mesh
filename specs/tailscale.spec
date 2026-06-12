# Charmed Tailscale/Headscale Solution Specification
# Status: DRAFT — under active design review

## Goals

Provide a charmed solution for integrating charmed workloads onto a tailnet.
Must work with both Tailscale and Headscale control planes.

### Use Cases

1. **Expose charmed workloads onto a tailnet** — make Juju-managed workloads
   reachable by other tailnet members (laptops, CI systems, other clusters).
2. **Mesh connectivity between tailnet members** — workloads across different
   Juju models/clusters can discover and communicate over the tailnet.

### Non-Goals / Constraints

- No blocking of cluster-local communication. The tailnet is purely additive —
  pods can still talk locally via local addresses AND over the tailnet via
  tailnet addresses.
- No CNI changes required. Tailscale operates above the CNI layer using
  userspace networking. Same-cluster tailnet traffic flows through proxy pods
  and WireGuard, riding on the existing CNI for underlying transport.

---

## Charms

### tailscale-config

Workloadless charm. Central credential authority for the tailnet.

**Credential Flow:**

The credential flow differs by backend, but downstream charms are unaware
of which backend is in use. They never communicate with any API — they
simply receive credentials and pass them to the Tailscale operator or
client.

*Tailscale backend:*
- User creates a "root" OAuth client in the Tailscale admin console with
  `oauth_keys:write` scope (and appropriate tags).
- User provides this credential to `tailscale-config` as a Juju secret.
- On relation to a downstream charm (`tailscale-k8s` or `tailscale-beacon`),
  `tailscale-config` uses the Tailscale API (`POST /api/v2/tailnet/-/keys`
  with `keyType: "client"`) to create a scoped child OAuth client with
  least-privilege scopes (e.g. `auth_keys`, `devices:core`) for that
  specific downstream charm.
- Each downstream charm receives its own isolated OAuth client credential.
- On relation removal, `tailscale-config` revokes the child client via
  `DELETE /api/v2/tailnet/-/keys/{keyId}`.

*Headscale backend:*
- User creates an API key on the Headscale server
  (`headscale apikeys create`) and provides it to `tailscale-config` as a
  Juju secret.
- On relation to a downstream charm, `tailscale-config` uses the Headscale
  API (`POST /api/v1/preauthkey`) to create a tagged pre-auth key for that
  specific downstream charm.
- Each downstream charm receives its own pre-auth key.
- On relation removal, `tailscale-config` expires the pre-auth key via
  `POST /api/v1/preauthkey/expire`.

*Backend configuration:*
- `tailscale-config` has a `backend` config option (`tailscale` or
  `headscale`).
- All API interaction is centralized in `tailscale-config`. Downstream
  charms are backend-agnostic — they receive credentials and pass them
  directly to the Tailscale operator or `tailscale up --auth-key`.

*Code structure for `tailscale-config`:*
- The backend-specific logic (API calls for credential creation, revocation,
  etc.) must be abstracted behind a common interface and separated into
  distinct files:
  - `backend_tailscale.py` — Tailscale OAuth API interactions
  - `backend_headscale.py` — Headscale REST API interactions
- The charm selects the appropriate backend implementation based on the
  `backend` config option.
- This keeps the two code paths cleanly separated and independently
  testable.

### tailscale-k8s

Deploys and manages the upstream Tailscale Kubernetes operator.

**Architecture:**
- Runs the upstream operator controller binary as-is via Pebble workload
  containers (eventually rebuilt with rockcraft).
- Does NOT reimplement the operator's logic. The charm manages the operator's
  configuration and lifecycle; the operator handles proxy pod lifecycle, state
  management, CRDs, etc.
- CRDs are installed by the operator itself via its `--install-crds` flag.
  The charm runs with `--trust` so no additional permissions are needed.

**Scaling:**
- The upstream operator does NOT support multiple replicas. It runs a
  tsnet.Server that joins the tailnet as a single device, uses no leader
  election, and writes to a single shared state Secret.
- The charm MUST enforce single-replica operation. If the user scales
  beyond 1 unit (`juju scale-application tailscale-k8s 2`), the charm
  sets BlockedStatus with message "Tailscale operator does not support
  multiple replicas" and refuses to start the operator on extra units.

**Credential Configuration (two modes):**
1. **Via `tailscale-config` relation** — receives a scoped child OAuth client
   automatically. This is the recommended mode.
2. **Manual config** — user provides OAuth client credentials (or auth key)
   directly as a Juju secret via charm config. For simpler deployments that
   don't need the full three-charm setup.

If both are present, the relation takes precedence.

**Configuration:**
- `login-server`: URL of the control plane. Empty for Tailscale SaaS, set to
  the Headscale URL for Headscale deployments.
- Operator tags, proxy tags, logging level, firewall mode, and other
  operational settings exposed as charm config options.

**Kubernetes Resources Created:**
The charm creates only the resources that are not covered by Juju/`--trust`:

- The operator's own Deployment, ServiceAccount, and RBAC (ClusterRole,
  ClusterRoleBinding, Role, RoleBinding) are NOT needed — Juju manages the
  pod via Pebble, and `--trust` grants cluster-admin to the charm's SA.
- The operator-oauth Secret is NOT needed — credentials are written directly
  to the container filesystem via Pebble (`container.push()`).

Resources the charm MUST create:

| # | Resource | Name | Purpose |
|---|----------|------|---------|
| 1 | ServiceAccount | `proxies` | Identity for proxy pods spawned by operator |
| 2 | Role (namespaced) | `proxies` | Proxy perms: secrets CRUD, events |
| 3 | RoleBinding (namespaced) | `proxies` | Binds proxies SA → Role |
| 4 | IngressClass | `tailscale` | Registers `tailscale.com/ts-ingress` controller |

- The `proxies` SA/Role/RoleBinding are required because proxy pods are
  separate pods (StatefulSets spawned by the operator) that do NOT inherit
  the charm's `--trust` permissions. The name `proxies` is hardcoded by the
  upstream operator. Created via lightkube on install.
- The IngressClass name is hardcoded to `tailscale` (not configurable).
- API server proxy mode is NOT supported in the initial scope. The
  `APISERVER_PROXY` env var is set to `false`, and the related resources
  (`kube-apiserver-auth-proxy` SA, `tailscale-auth-proxy` ClusterRole and
  ClusterRoleBinding) are NOT created.

**Credential injection:**
- Credentials are pushed to the container via Pebble:
  `container.push("/oauth/client_id", ...)` and
  `container.push("/oauth/client_secret", ...)`
- Operator env vars `CLIENT_ID_FILE=/oauth/client_id` and
  `CLIENT_SECRET_FILE=/oauth/client_secret` point to these files.

CRDs installed by operator: connectors, proxyclasses, proxygroups, dnsconfigs,
tailnets, recorders, proxygrouppolicies.

### tailscale-beacon-k8s

Lives in the user application's model. Acts as an entrypoint to the tailnet
using the `ingress` relation.

**How it works:**
1. User deploys `tailscale-beacon-k8s` in the same model as their app.
2. User relates their app to `tailscale-beacon-k8s` via the `ingress` relation.
3. On relation, the beacon receives the app's service name and port info.
4. The beacon creates a LoadBalancer Service:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: <app-name>-tailscale
  annotations:
    tailscale.com/hostname: <app-name>
spec:
  type: LoadBalancer
  loadBalancerClass: tailscale
  selector:
    app.kubernetes.io/name: <app-name>
  ports:
    - port: <app-port>
```

5. The upstream Tailscale operator (running in the `tailscale-k8s` model)
   detects this Service cluster-wide via its ClusterRole, creates a proxy
   StatefulSet, and the app appears on the tailnet.

**Credentials:** None needed. The beacon only creates Kubernetes resources.
The operator (managed by `tailscale-k8s`) holds the OAuth credentials and
handles all tailnet registration.

### tailscale-beacon

Machine subordinate charm. Deploys and runs the Tailscale snap.

**Subordinate Design:**
- Relates to principal charms via the `juju-info` relation (available on all
  charms by default).
- Installs the `tailscale` snap on the machine, runs
  `tailscale up --auth-key=<key> --advertise-tags=<tags>`.
- The entire machine becomes a tailnet node. All services listening on that
  machine are reachable via its tailnet IP.
- Finer-grained port control is handled via Tailscale ACLs on the
  coordination server side.

**Credential Configuration (two modes):**
1. **Via `tailscale-config` relation** — receives a scoped child OAuth client
   automatically.
2. **Manual config** — user provides credentials directly as a Juju secret.

**Multi-Principal Handling:**
When related to multiple principals on the same machine, Juju creates
multiple subordinate units. Since only one `tailscaled` daemon can run per
machine, the charm uses filesystem-based reference counting:

- Directory: `/var/lib/tailscale-beacon/units/`
- On `install`: create file `<unit-name>` in the directory. If this is the
  first file (directory was empty/didn't exist), install the snap, configure
  credentials, run `tailscale up`.
- On `stop`/`remove`: delete the `<unit-name>` file. If the directory is now
  empty, run `tailscale down`, remove credentials, optionally remove the snap.

This is safe because Juju serializes hook execution per unit on the same
machine.

---

## Relations

### tailscale-config → tailscale-k8s / tailscale-beacon
- Custom interface for distributing credentials.
- `tailscale-config` (provider) sends credentials appropriate to the backend:
  - Tailscale: child OAuth client ID + client secret
  - Headscale: pre-auth key
  - Plus: login server URL, tags
- Downstream charm (requirer) receives credentials and passes them directly
  to the operator/client. It is backend-agnostic.
- NOTE (open): exact relation data field names not yet finalized — see Open
  Questions.

### ingress (application charm → tailscale-beacon-k8s)
- Standard `ingress` relation interface.
- Application charm provides: service name, port, model name.
- `tailscale-beacon-k8s` creates the LoadBalancer Service to expose the app
  on the tailnet.

### juju-info (principal charm → tailscale-beacon)
- Standard `juju-info` subordinate relation.
- No application-level data exchanged — the beacon makes the entire machine
  a tailnet node regardless of which principal it's related to.

---

## Open Questions

- Precedence behavior when both relation and manual config are present on
  `tailscale-k8s` or `tailscale-beacon` (error vs relation-wins).
  (Current working assumption: relation takes precedence.)
- Headscale credential API details — exact endpoints and authentication
  mechanism for Headscale's API.
- Exact relation data field names for the `tailscale-config` credential
  relation (e.g. `client-id`, `client-secret`/`auth-key`, `login-server`,
  `tags`).
- Cleanup behavior on `tailscale-k8s` removal — whether to delete CRDs
  (destructive, cascades to user ProxyGroups/Connectors) or only remove the
  charm-managed resources (proxies SA/RBAC, IngressClass).
