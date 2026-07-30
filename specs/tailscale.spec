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

**Mesh direction asymmetry (K8s):** machine workloads (`tailscale-beacon`) join
the tailnet host-wide and get bidirectional mesh for free. K8s workloads do
NOT: the operator's ingress `LoadBalancer` proxy is inbound-only, so a pod is
*reachable* but cannot *initiate* tailnet connections. Therefore K8s
**egress** (a pod dialing another tailnet member) is IN SCOPE. The exact
mechanism is **DEFERRED** — see the FLAGGED item in Open Questions. We will
build the rest of the charms first and return to egress before it is needed.

### Non-Goals / Constraints

- No blocking of cluster-local communication. The tailnet is purely additive —
  pods can still talk locally via local addresses AND over the tailnet via
  tailnet addresses.
- No CNI changes required. Tailscale operates above the CNI layer using
  userspace networking. Same-cluster tailnet traffic flows through proxy pods
  and WireGuard, riding on the existing CNI for underlying transport.

---

## Architecture & Topology

- **One `tailscale-k8s` operator per cluster.** This is forced by the upstream
  design (single tsnet device, shared state Secret, single-replica) and is the
  charm's assumed deployment model. Any number of `tailscale-beacon-k8s`
  instances may exist across many application models on that cluster.
- **Implicit coordination — no Juju relation between `tailscale-beacon-k8s`
  and `tailscale-k8s`.** The beacon simply creates a `LoadBalancer` Service
  with `loadBalancerClass: tailscale`; the cluster-wide operator watches for
  such Services and does the tailnet registration. App teams therefore never
  need a cross-model relation to the operator and need not know which model it
  runs in. Readiness flows back through the Service status
  (`ProxyReady` / `.status.loadBalancer.ingress`), not through relation data.
- **Second-operator protection.** `tailscale-k8s` should detect the presence
  of another operator on the cluster and set BlockedStatus, provided a
  reasonably simple detection exists (e.g. an already-present operator marker
  such as the shared state Secret / IngressClass / a well-known label). If no
  simple, reliable signal exists, this is downgraded to documented user error
  rather than a complex active-election mechanism.
- **`tailscale-beacon-k8s` is useless on its own.** It only creates Kubernetes
  resources; without a `tailscale-k8s` operator running somewhere in the
  cluster, the `LoadBalancer` Service it creates is never reconciled onto the
  tailnet. This coupling is by design (the operator is the single tailnet
  authority for the cluster).
- **Model layout must not affect functionality.** No particular co-location is
  prescribed: `tailscale-config`, `tailscale-k8s`, and the app +
  `tailscale-beacon-k8s` may live in the same model or separate models, on the
  same cluster or (for `tailscale-config`, which is only an API client holding
  no cluster state) off-cluster. All arrangements are supported via in-model
  relations or cross-model relations (CMRs) as appropriate. Consequences:
  - A single `tailscale-config` is **multi-tenant**: it can serve many
    `tailscale-k8s` / `tailscale-beacon` downstreams across many models and
    clusters at once. It is NOT a singleton assumption.
  - Credential minting is keyed **per relation** (each downstream gets its own
    child OAuth client / pre-auth key), which is what makes multi-tenancy work
    naturally.
  - `tailscale-config` holds no cluster/tailnet state beyond what it needs to
    talk to the control-plane API, so it can be placed anywhere reachable.

### Backend support scope

- **Both Tailscale and Headscale must work on day one, including credential
  distribution via `tailscale-config`.** For both backends, `tailscale-config`
  is the credential authority that mints per-downstream credentials (child
  OAuth clients for Tailscale, pre-auth keys for Headscale) and distributes
  them to `tailscale-k8s` / `tailscale-beacon`. This downstream distribution
  path is day-one for Headscale, not deferred.
- **What differs day one is how `tailscale-config` obtains its *own* root
  credentials/config:**
  - Day one (both backends): the root credential and control-plane URL are
    supplied to `tailscale-config` via its **own charm config** — a Tailscale
    root OAuth client, or a Headscale API key + Headscale server URL.
  - **Deferred (later phase):** a relation between `tailscale-config` and the
    existing third-party **headscale charm** that would let `tailscale-config`
    obtain the Headscale API key / server URL automatically instead of via
    config. Not required day one.
- **Consequence:** the `backend_headscale.py` seam in `tailscale-config` IS
  day-one work (it must mint/revoke Headscale pre-auth keys via the Headscale
  API). Only the *upstream* integration with the headscale charm is deferred.
- Downstream charms stay backend-agnostic: they receive credentials from
  `tailscale-config` (or manual config) and pass the `login-server` + auth key
  to the operator / `tailscale up`. Tailscale vs Headscale is expressed by the
  `login-server` value.

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
  `oauth_keys:write` scope. The tags carried by this root client must own
  (in the tailnet `tagOwners`) whatever operator/proxy tags `tailscale-k8s`
  is configured to apply (default `tag:k8s-operator` and `tag:k8s`).
- User provides this credential to `tailscale-config` as a Juju secret.
- Scope capping is enforced server-side: a child client minted from an
  `oauth_keys`-scoped token can only carry a subset of the parent's scopes.
  Empirically verified — requesting `all` or `policy_file` returns
  `403 actor cannot set scopes: [...]`. The per-downstream child-client
  model is therefore NOT a privilege-escalation vector on Tailscale.
  (Corollary: because of capping, the root client must carry the UNION of
  all scopes it will delegate — e.g. `oauth_keys` to mint children PLUS
  `auth_keys`/`devices:core` for the children to use.)
- On relation to a downstream charm (`tailscale-k8s` or `tailscale-beacon`),
  `tailscale-config` uses the Tailscale API (`POST /api/v2/tailnet/-/keys`
  with `keyType: "client"`) to create a scoped child OAuth client for that
  specific downstream charm. The child is minted carrying the SAME tags as
  the parent (root) client — the parent can always grant its own tags to a
  child by exact match, so this is the maximal safe tag set and needs no
  additional `tagOwners` entries for the child's identity.
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

*Device approval / pre-authorization:*
- Credentials minted by `tailscale-config` MUST be created with
  `preauthorized=true` so that devices skip manual approval even when the
  tailnet has device approval enabled.
- Device approval is an opt-in tailnet feature (off by default). It is only
  hit when device approval is enabled AND a non-pre-authorized key is used.
- When an admin configures a downstream charm manually (not via
  `tailscale-config`) with a non-pre-authorized key on an approval-enabled
  tailnet, the operator/client device lands in `NeedsMachineAuth`. Note that
  each new device (the operator AND every proxy pod) requires its own
  approval — it is not a one-time action.

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

If BOTH are present, neither wins — the charm sets BlockedStatus and refuses
to proceed until the conflict is resolved (the ambiguity is treated as user
error).

**Configuration:**
- `login-server`: URL of the control plane. Empty for Tailscale SaaS, set to
  the Headscale URL for Headscale deployments.
- Operator tags, proxy tags, logging level, firewall mode, and other
  operational settings exposed as charm config options.

**Tag Model:**
- The operator/proxy tags are configurable in `tailscale-k8s`:
  `operator-tags` (the operator device, env `OPERATOR_INITIAL_TAGS`) and
  `proxy-tags` (the proxy pods, env `PROXY_TAGS`). Each is a SET of tags,
  expressed as a comma-separated string (the operator parses both with
  `strings.Split(..., ",")`), defaulting to the single tags
  `tag:k8s-operator` and `tag:k8s` respectively. Users may override them
  with one or more tags.
- Child clients minted by `tailscale-config` carry the SAME tags as the
  parent (root) client — they inherit the parent's tag identity rather than
  hardcoding the k8s tags. The parent can always grant its own tags to a
  child (exact match), so no extra `tagOwners` entries are needed for the
  child itself.
- The tailnet ACL/policy file (`tagOwners`) is a user-managed prerequisite.
  The standard operator pattern is:
  ```
  "tagOwners": {
      "tag:k8s-operator": [],                  // applied to the operator device
      "tag:k8s":          ["tag:k8s-operator"]  // applied to proxy pods
  }
  ```
  The credential must CARRY the operator tag (`tag:k8s-operator`) so the
  operator can authenticate its own device by exact match. It does NOT need
  to carry the proxy tag (`tag:k8s`): the operator mints proxy auth keys, and
  those succeed because the operator tag OWNS the proxy tag in `tagOwners`
  (a hierarchy relationship). The charm does NOT mutate the ACL (no
  `policy_file` write scope required).
- If the user overrides `operator-tags`/`proxy-tags`, they must update
  `tagOwners` accordingly: the credential must carry the new operator tag,
  and the operator tag must own the new proxy tag.

**Graceful Tag-Ownership Detection:**
The user owns the `tagOwners` setup, so `tailscale-k8s` must detect a wrong
or missing configuration and report it clearly. `tailscale-k8s` is the only
charm that holds both inputs — the credential it received AND the
`operator-tags`/`proxy-tags` it is configured to apply — so it performs a
single self-check at reconcile time, before handing the credential to the
operator.

The check is a side-effect-free read of the credential's own carried tags:
`GET /api/v2/tailnet/-/keys/{keyId}` (the keyId is the OAuth client's id).
Any credential may read its own key regardless of scope — the Tailscale docs
state every scope allows `GET .../keys/:keyID` "for the key in use" — so no
extra scope and no device registration is required. The response includes
the credential's `scopes` and `tags`.

Only the OPERATOR tag set is checked locally, because only it is applied by
exact match. `tailscale-k8s` verifies `operator-tags ⊆ carried tags` (every
configured operator tag must be carried by the credential):
- pass → authoritative. The operator will authenticate its own device by
  exact match (needs no `tagOwners` entry). Proceed.
- fail → BlockedStatus naming the specific operator tag(s) the credential
  does not carry, so the operator can never register. This is a definite
  misconfiguration the charm can report with certainty.

The PROXY tag is deliberately NOT checked locally. In the standard pattern
it is owned-by-hierarchy rather than carried, so its grantability depends on
`tagOwners` (unreadable without `policy_file:read`). A proxy-tag problem
surfaces at runtime: the operator's `CreateKey` for the proxy tag fails →
proxy pods never authenticate → the exposed Service never receives a
LoadBalancer ingress address.

Runtime backstop (part of normal status reconciliation): watch operator
device registration and the exposed Service's `ProxyReady` condition /
LoadBalancer ingress on a timer. Startup → WaitingStatus; timeout with no
ingress address or a `ProxyInvalid`/`ProxyFailed` condition → BlockedStatus,
scraping operator pod logs for `CreateKey`/tag-authorization errors to name
the likely `tagOwners` fix for the proxy tag.

(The exact field name `tags` on the GET-key response, and its presence for
OAuth clients specifically, should be confirmed empirically — as was done
for the scope-rejection shape.)

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
    tailscale.com/hostname: <model>-<app-name>
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

The `tailscale.com/hostname` is model-qualified (`<model>-<app-name>`) so the
tailnet device name is unique across models — the operator reconciles Services
cluster-wide, so two apps of the same name in different models would otherwise
collide on the tailnet (Tailscale would silently append a numeric suffix). The
`<model>-<app>` order matches Traefik's default ingress path prefix.

**Credentials:** None needed. The beacon only creates Kubernetes resources.
The operator (managed by `tailscale-k8s`) holds the OAuth credentials and
handles all tailnet registration.

**Ingress URL Response:**

The beacon returns an `ingress` `url` of the form
`http://<tailnet-hostname>:<port>/` where:
- `<tailnet-hostname>` is the MagicDNS name read from the LoadBalancer
  Service's `.status.loadBalancer.ingress` (populated by the operator once
  the proxy is up).
- `<port>` is the original app port from the requirer.
- The path is the ROOT (`/`) — there is NO `[model]-[unit]` path prefix,
  because each exposed service gets its own MagicDNS hostname rather than
  path-based routing.

Timing:
- The beacon does NOT write the `url` to relation data until
  `.status.loadBalancer.ingress` is populated.
- During reconcile, the charm waits (within hook execution) for the address
  up to a reasonable timeout. If the address becomes available, it writes
  the `url`.
- If the timeout elapses and the address is still unavailable, the charm
  raises an exception AFTER the reconcile completes (deferred-exception
  pattern), so other operations finish first.

**Status Reporting:**

The beacon cannot directly observe the proxy pod (it lives in the
`tailscale-k8s` model). Instead, it reads two signals that the operator
writes onto the beacon's own LoadBalancer Service:
- `.status.loadBalancer.ingress` — populated with the tailnet hostname/IPs
  when the proxy is ready.
- `.status.conditions[ProxyReady]` — a condition the operator sets with
  reasons: `ProxyCreated` (ready), `ProxyPending` (waiting), `ProxyInvalid`
  / `ProxyFailed` (errors). Note: a stuck `NeedsMachineAuth` is NOT
  distinguishable from normal startup — both appear as `ProxyPending` with
  message "no Tailscale hostname known yet, waiting for proxy pod to finish
  auth".

Reporting rules:
- **ActiveStatus** when `.status.loadBalancer.ingress` is populated. Show the
  tailnet hostname in the status message.
- **WaitingStatus** when `ProxyReady` is `ProxyPending` — surface the
  operator's message.
- When `ProxyReady` is `ProxyInvalid` or `ProxyFailed`: raise an exception
  and write an error log, surfacing the operator's message as the exception
  string. This MUST happen at the END of the charm's reconcile function so
  it does not block other operations from completing first.
- After a reasonable timeout still in `ProxyPending`, log a warning
  mentioning possible device approval (`NeedsMachineAuth`) so the user knows
  to check the admin console.

The same status-reporting approach applies to `tailscale-k8s` for the
operator's own device: surface `NeedsMachineAuth` as BlockedStatus with a
message directing the admin to approve the device or use a pre-authorized
key.

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
- Uses the standard `ingress` v2 relation interface (provider/requirer).
- Requirer (the app) sends: `name` (app name), `model`, `port` (app
  databag), and `host` (unit databag). These map cleanly to what the beacon
  needs to create the LoadBalancer Service.
- Provider (the beacon) returns a `url` field (typed `AnyHttpUrl`).
- DECISION: Implement the standard `ingress` interface now for compatibility
  with the existing charm ecosystem. The `ingress` interface is the
  established way to request HTTP routing, so the returned URL is correct for
  HTTP apps (not merely synthetic). A custom interface for raw TCP/L3
  (non-HTTP) workloads can be added later.
- SCOPE (day one): only HTTP workloads are supported. Non-HTTP workloads
  can NOT use the `ingress` relation and simply "ignore the `http://`
  scheme" — an `ingress` requirer is written to work against ANY ingress
  provider, so it must be able to assume the returned URL is genuinely HTTP.
  Non-HTTP consumers are therefore unsupported until we add a more generic
  (raw TCP/L3) relation later.
- `tailscale-beacon-k8s` creates the LoadBalancer Service to expose the app
  on the tailnet.

### juju-info (principal charm → tailscale-beacon)
- Standard `juju-info` subordinate relation.
- No application-level data exchanged — the beacon makes the entire machine
  a tailnet node regardless of which principal it's related to.

---

## Open Questions

- Credential rotation / update propagation (root-credential rotation
  re-minting children, child credential lifetime/rotation) — deferred
  implementation detail, not a day-one architecture question.
- **[FLAGGED — revisit after the rest of the charms are implemented]
  K8s egress mechanism (how a K8s pod initiates connections to arbitrary
  tailnet members).** K8s workloads get inbound reachability for free but not
  outbound. "Transparent, zero-app-change, reach-anything" egress is NOT
  achievable within our current constraints; each viable path relaxes a
  different constraint:
  1. **Per-target `ExternalName` egress (operator-native).** App dials a normal
     cluster DNS name; transparent and backend-uniform, but egress targets
     must be declared per-destination (not "reach anything"). Would use an
     egress relation (app as client → a K8s charm creates the `ExternalName`
     Service → returns the in-cluster address to dial). Which charm owns this
     (e.g. `tailscale-beacon-k8s` gaining a second, egress-side relation vs a
     dedicated charm) is part of what is deferred.
  2. **Shared userspace SOCKS5 / HTTP egress proxy.** One proxy pod reaches
     anything on the tailnet, but the application must be proxy-aware
     (`HTTP_PROXY`/`ALL_PROXY`/SOCKS5). Not transparent.
  3. **Tailnet gateway routing the CGNAT range + MagicDNS.** Transparent and
     reach-anything, but requires per-pod routing/DNS changes — collides with
     the "No CNI changes" non-goal and needs config injected into the app pod.
  Constraint that rules out the machine-style "whole workload on the tailnet"
  trick on K8s: in Juju K8s each charm is its own StatefulSet/pod, so
  `tailscale-beacon-k8s` cannot inject a tailscale sidecar into a neighbor
  charm's pod. Leaning toward (1) as the day-one primitive with (2) as an
  opt-in, but the decision is deferred until implementation is underway.
- Headscale credential API details — exact endpoints and authentication
  mechanism for Headscale's API. The Tailscale scope-capping guarantee is
  Tailscale-specific; the Headscale equivalent (API keys + pre-auth keys,
  no OAuth-client hierarchy) needs its own verification.
- Exact relation data field names for the `tailscale-config` credential
  relation (e.g. `client-id`, `client-secret`/`auth-key`, `login-server`,
  `tags`).
- Cleanup behavior on `tailscale-k8s` removal — whether to delete CRDs
  (destructive, cascades to user ProxyGroups/Connectors) or only remove the
  charm-managed resources (proxies SA/RBAC, IngressClass).

## Resolved Decisions

- Tag model: operator/proxy tags are configurable in `tailscale-k8s`
  (`operator-tags`/`proxy-tags`, default `tag:k8s-operator`/`tag:k8s`).
  Child clients minted by `tailscale-config` inherit the parent client's
  tags. The user is responsible for `tagOwners` such that the parent's tags
  own the configured operator/proxy tags; `tailscale-k8s` checks only the
  operator tag locally (`operator-tags ⊆ carried tags` via
  `GET .../keys/{keyId}`, allowed by any scope) and reports a missing
  operator tag as BlockedStatus. The proxy tag follows the standard
  `tagOwners` hierarchy (operator tag owns proxy tag) and its failures are
  detected at runtime (Service never gets a LoadBalancer address), not by
  editing the ACL.
- The operator-tag check is STRICT: every configured operator tag must be
  literally carried by the credential (`operator-tags ⊆ carried tags`), even
  in the multi-tag-override case where some tags might otherwise be grantable
  via a `tagOwners` hierarchy we cannot read. Decision: prefer a definite,
  authoritative BlockedStatus over a permissive "warn + defer to runtime"
  path for operator tags; the user must carry all operator tags directly.
- Child OAuth clients are scope-capped by Tailscale (empirically verified):
  an `oauth_keys`-scoped token cannot mint a child client with scopes it
  does not hold — `all` and `policy_file` both return
  `403 actor cannot set scopes: [...]`, while a same-scope (`oauth_keys`)
  child is created successfully. The per-downstream credential model is safe.
- `tailscale-beacon-k8s` uses the standard `ingress` v2 interface now for
  ecosystem compatibility. A custom interface for raw TCP/L3 workloads may
  be added later. Day one this means only HTTP workloads are supported:
  non-HTTP apps cannot use the `ingress` relation (a requirer must work with
  any ingress provider and therefore must be able to trust the `http://`
  scheme), so they wait for the future generic relation.

- When both the `tailscale-config` relation and manual config are present,
  the charm BLOCKS rather than picking a winner. Applies to both
  `tailscale-k8s` and `tailscale-beacon`.
- `tailscale-config` is OPTIONAL. Every downstream charm (`tailscale-k8s`,
  `tailscale-beacon`) is fully functional standalone via manual config;
  `tailscale-config` exists to automate credential lifecycle (minting,
  rotation, revocation) and is the recommended default at scale but is never
  required. (The choice was between "optional" and "effectively required";
  optional wins — manual mode is a first-class supported path, not just a
  dev-only escape hatch.)
- No automatic credential revocation in manual mode. A manually-supplied
  credential is fully user-owned; on charm removal the downstream charm does
  NOT attempt to revoke/expire it (that would also force the credential to
  carry teardown-only API scopes it otherwise wouldn't need). Automatic
  revocation on relation removal remains a value-add exclusive to
  `tailscale-config` (relation mode).
- Credentials minted by `tailscale-config` are created with
  `preauthorized=true`; `NeedsMachineAuth` is surfaced as BlockedStatus when
  it occurs (manual non-pre-authorized keys on approval-enabled tailnets).
