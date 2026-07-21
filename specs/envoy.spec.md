# Envoy AI Gateway Juju Charm(s) — Design Specification

*Status: DRAFT — Under active design discussion*

---

## Overview

Design specification for a Juju charm (or set of charms) to deploy, configure, and operate the **Envoy AI Gateway** stack within a Juju-managed Kubernetes environment. The goal is to replicate the functionality of the upstream Envoy AI Gateway deployment (Envoy Gateway + AI Gateway controller + Gateway API CRDs) as Juju-native charms.

---

## Target Stack

The upstream deployment consists of six layers that the charm(s) must cover:

### Layer 1: Gateway API CRDs (v1.4.1)
```
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
```
Kubernetes Gateway API Custom Resource Definitions (`GatewayClass`, `Gateway`, `HTTPRoute`, `GRPCRoute`, `ReferenceGrant`, etc.). Prerequisite CRD schemas only, no running workloads.

### Layer 2: Gateway API Inference Extension CRDs (v1.3.0)
```
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${GIE_VERSION}/manifests.yaml"
```
Installs the Gateway API Inference Extension CRD set: **`InferencePool`** (API group `inference.networking.k8s.io`, stable) plus the experimental group (`inference.networking.x-k8s.io`) — `InferencePool` (experimental copy), `InferenceObjective`, `InferenceModelRewrite`, and `InferencePoolImport`. `InferencePool` represents a pool of model-serving endpoints (e.g., vLLM pods) and extends the Gateway API to support inference-aware routing. This installs **CRDs only** — no running workloads.

**Full upstream bundle.** The charm bundles the upstream v1.3.0 `manifests.yaml` verbatim. The experimental group is required in practice: scheduler-mode workloads (e.g., KServe `LLMInferenceService` deployed with the `llm-d-inference-scheduler` image) consume `InferenceObjective` (`inference.networking.x-k8s.io/v1alpha2`) at startup and crash-loop without it (see [#128](https://github.com/canonical/service-mesh/issues/128)). Note that the pre-v1.3.0 `InferenceModel` CRD has been **removed upstream**; its model-routing role is now served by `InferenceObjective`.

The **Endpoint Picker (EPP)** — an ext-proc server that performs kv-cache-aware, request-cost-aware load balancing across model server endpoints — is **not** installed by this charm. EPP is deployed **per-`InferencePool`** at runtime (via the upstream `inferencepool` Helm chart) by whoever provisions the pool (e.g., KServe or the user). Like KServe itself, EPP is an external, out-of-scope component from the charm's perspective.

### Layer 3: Envoy Gateway Controller (v1.6.3)
```
helm upgrade -i eg oci://docker.io/envoyproxy/gateway-helm \
  --version "${ENVOY_GATEWAY_VERSION}" \
  --namespace envoy-gateway-system \
  --create-namespace \
  -f envoy-gateway-values.yaml \
  -f envoy-gateway-values-addon.yaml \
  --wait --timeout 300s
```
Go-based controller in `envoy-gateway-system` that watches Gateway API resources and translates them into Envoy xDS configuration. Provisions Envoy Proxy pods as the data plane. Configured with:
- **AI Gateway extension manager hooks**: tells Envoy Gateway to call the AI Gateway controller (gRPC at `ai-gateway-controller.envoy-ai-gateway-system.svc.cluster.local:1063`) for xDS translation on listeners, routes, clusters, and secrets.
- **Backend API and EnvoyPatchPolicy** enabled for AI service backends.
- **InferencePool** (`inference.networking.k8s.io/v1`) registered as a recognized backend resource for inference-aware routing.

### Layer 4: AI Gateway CRDs (v0.5.0)
```
helm upgrade -i aieg-crd oci://docker.io/envoyproxy/ai-gateway-crds-helm \
  --version "${ENVOY_AI_GATEWAY_VERSION}" \
  --namespace envoy-ai-gateway-system \
  --create-namespace
```
CRDs for AI-specific resources (5 total): `AIGatewayRoute`, `AIServiceBackend`, `BackendSecurityPolicy`, `MCPRoute`, `GatewayConfig`.

### Layer 5: AI Gateway Controller (v0.5.0)
```
helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm \
  --version "${ENVOY_AI_GATEWAY_VERSION}" \
  --namespace envoy-ai-gateway-system \
  --create-namespace \
  --wait --timeout 300s
```
Controller in `envoy-ai-gateway-system` that:
- Watches AI Gateway CRs (`AIGatewayRoute`, `AIServiceBackend`, `BackendSecurityPolicy`)
- Generates Envoy Gateway resources (`HTTPRoute`, `HTTPRouteFilter`)
- Serves the Envoy Gateway Extension Server protocol (gRPC, port 1063) for xDS fine-tuning
- Injects an ExtProc sidecar into Envoy Proxy pods via admission webhook — handles AI-specific request/response processing (model routing, API format translation between providers, token counting, provider auth) over a local Unix Domain Socket

### Layer 6: Gateway + GatewayClass Resources
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: envoy   # constant, cluster-scoped, owned by the controller charm
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
  parametersRef:
    group: gateway.envoyproxy.io
    kind: EnvoyProxy
    name: <ENVOY_PROXY_NAME>        # controller's EnvoyProxy
    namespace: <CONTROLLER_MODEL>   # controller's own model
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: <GATEWAY_NAME>
  namespace: <GATEWAY_NAMESPACE>
spec:
  gatewayClassName: envoy
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All
  infrastructure:
    labels:
      serving.kserve.io/gateway: <GATEWAY_NAME>
```
Runtime resources: the **`GatewayClass` is created once by the controller charm** (constant name `envoy`), registering Envoy Gateway as the implementation and carrying the `parametersRef` → the controller's `EnvoyProxy` so every provisioned proxy inherits the Juju-topology stats tags and OTLP sink. The GatewayClass is cluster-scoped and shared by **all** ingress deployments. Each **`Gateway` is created by an ingress charm** in its own model, referencing `gatewayClassName: envoy`; it creates an HTTP listener on port 80, accepts routes from all namespaces, labeled for KServe integration. Triggers Envoy Proxy pod provisioning.

### External Dependency: KServe (v0.17.0)
KServe is **assumed to already exist** on the cluster. The charm(s) do not install or manage KServe — they only integrate with it via the Gateway's `serving.kserve.io/gateway` label.

---

## Charm Architecture

### Charm 1: `envoy-controller-k8s` (control plane)

Installs all platform infrastructure (layers 1–5):
- Gateway API CRDs
- Gateway Inference Extension CRDs (stable `InferencePool` only; EPP is **not** installed — see Layer 2) (Only when AI features are enabled)
- Envoy Gateway Controller (with AI Gateway extension manager config)
- AI Gateway CRDs (Only when AI features are enabled)
- AI Gateway Controller

Also creates the **single, shared `GatewayClass`** (constant name `envoy`) that binds Gateways to Envoy Gateway and carries the `parametersRef` → the controller's own `EnvoyProxy` config. **Does not** create any `Gateway` resources — those belong to the ingress charm(s).

#### Pod Structure

One pod with two Pebble workload containers:
- **Envoy Gateway controller** — Go binary, watches Gateway API resources, translates to xDS, provisions Envoy Proxy pods
- **AI Gateway controller** — Go binary, watches AI Gateway CRs, serves Extension Server (gRPC port 1063), serves ExtProc sidecar admission webhook (port 9443)

#### Requires Trust

Deployed with `juju deploy --trust` or `juju trust`. The charm's ServiceAccount receives `cluster-admin`, eliminating the need to manage RBAC resources.

#### lightkube-managed Resources

All charm-managed Kubernetes objects (CRDs and the webhook) are managed through the **`KubernetesResourceManager` (KRM)** helper from `canonical_service_mesh` (lightkube-based). KRM provides a declarative `reconcile()` that: stamps app-scoped ownership labels on every resource, lists currently-owned resources by label selector, deletes the set-difference (stale) resources, and applies the desired set via **server-side apply (SSA)**. See [Scaling Behavior](#scaling-behavior) for why this makes concurrent multi-unit reconciliation safe.

| Resource | Count | Purpose |
|---|---|---|
| CRDs (Gateway API + GIE + AI Gateway) | ~23 | Applied from bundled YAML on install (via KRM) |
| MutatingWebhookConfiguration (ExtProc sidecar injector) | 1 | Injects AI Gateway ExtProc sidecar into Envoy Proxy pods (via KRM) |
| `EnvoyProxy` (`gateway.envoyproxy.io/v1alpha1`) | 1 | Default proxy configuration. Carries the OTLP metrics sink (endpoint from the `otlp` relation) **and** fixed Juju-topology stats tags (see [Proxy Metrics Topology](#proxy-metrics-topology)). Referenced by the controller's own `GatewayClass.spec.parametersRef` (via KRM), so all proxies share it. |
| `GatewayClass` (`gateway.networking.k8s.io/v1`) | 1 | The single, cluster-scoped, shared class (constant name `envoy`). Carries `controllerName` + `parametersRef` → the `EnvoyProxy` above. Ingress charms reference it by name (via KRM). |

#### Pebble-managed

| Concern | Mechanism |
|---|---|
| Controller processes | Pebble services (one per container) |
| Controller config files | `container.push()` |
| Controller health | Pebble health checks (`/healthz`, `/readyz`) per controller, `on-check-failure: restart` |
| TLS certs | Received from `tls-certificates` relation, pushed to containers via Pebble |

#### TLS Certificate Contract

The ExtProc admission webhook and the Extension Server are both fronted by the charm's own Kubernetes **Service** (both controllers run in the same pod). The `MutatingWebhookConfiguration` references the backend via **`clientConfig.service`** (namespace/name/port `9443`) — **not** `clientConfig.url` — so the API server dials the Service DNS name. For the API server's TLS handshake to succeed, the served certificate's SANs must contain that exact name. The charm therefore requests, over `tls-certificates`, a single server certificate whose **DNS SANs** are:

- `<app>.<model>.svc.cluster.local` (primary; also the computed Extension Server FQDN, port `1063`)
- `<app>.<model>.svc`
- `<app>.<model>`
- `<app>` (bare, defensive)

The **issuing CA** from the same relation is reused verbatim as the `MutatingWebhookConfiguration.caBundle`, guaranteeing the webhook's trust anchor matches the served cert. If the SAN does not match the dialed name, every admission call fails (`x509: certificate is valid for ...`) and Envoy Proxy pods silently never receive the ExtProc sidecar — hence the SAN set is pinned here as a contract and asserted by a unit test.

#### Relations

| Interface | Direction | Purpose |
|---|---|---|
| `tls-certificates` | requires | TLS certs for webhook server + Extension Server |
| `otlp` | requires | OTLP endpoint + alert/recording rules for controller and Envoy Proxy metrics |
| `grafana_dashboard` | provides | Ships Grafana dashboard JSON for both controller health and Envoy Proxy data plane metrics. Both use standard Juju topology labels (proxy metrics are tagged via the default `EnvoyProxy` — see [Proxy Metrics Topology](#proxy-metrics-topology)). |

#### Proxy Metrics Topology

Envoy Proxy pods are provisioned by the Envoy Gateway controller at runtime, not by Juju, so by default their metrics carry only Envoy's own labels (`gateway_name`, `gateway_namespace`) and **no Juju topology**. To make data-plane metrics first-class COS citizens, the charm manages a default **`EnvoyProxy`** resource whose `spec.bootstrap` injects **fixed `stats_tags`** (Envoy `fixed_value`) stamping this app's Juju topology onto every proxy stat:

- `juju_model`, `juju_model_uuid`, `juju_application`, `juju_charm`
- `juju_unit` is **omitted** — there are many proxy pods per app, and COS alert scoping is app-level.

The same `EnvoyProxy` also carries the `telemetry.metrics.sinks` OpenTelemetry sink (endpoint from the `otlp` relation). Because a single shared `EnvoyProxy` backs every ingress deployment, its static Juju-topology stats tags reflect the **controller's** topology; per-ingress breakdown comes from Envoy Gateway's built-in `gateway_name`/`gateway_namespace` metric labels rather than per-ingress Juju tags. The controller's `GatewayClass` references this resource via `spec.parametersRef`.

**Two telemetry surfaces.** Envoy Gateway emits metrics from two distinct places, and the `otlp` relation feeds both:

- **Control-plane** (the Envoy Gateway controller's own metrics) \u2014 the OTLP sink is configured in the `EnvoyGateway` **config file** the charm pushes to the controller container via Pebble.
- **Data-plane** (the Envoy Proxy pods' metrics) \u2014 the OTLP sink is configured in the default **`EnvoyProxy` resource** (`telemetry.metrics.sinks`), alongside the fixed Juju-topology stats tags.

Both sinks use the same endpoint from the `otlp` relation; both are removed when the relation is broken.

#### Runtime-created Resources (by the controllers, not the charm)

- Envoy Proxy Deployments, Services, ConfigMaps (by Envoy Gateway controller)
- HTTPRoute, HTTPRouteFilter (by AI Gateway controller from AIGatewayRoute CRs)
- ExtProc config Secrets (by AI Gateway controller)
- ExtProc sidecar containers in Envoy Proxy pods (by admission webhook)

### Charm 2: `envoy-ingress-k8s` (gateway resources)

A separate charm that manages user-facing Gateway resources:
- `GatewayClass` — registers Envoy Gateway as the Gateway API implementation
- `Gateway` — HTTP/HTTPS listeners, KServe integration labels

This charm is **not designed in this spec** — it is a separate effort. It would likely relate to `envoy-controller-k8s` to discover the controller name, namespace, etc.

### Future work: `gateway-api-crds` charm
Layers 1 and 2 (Gateway API CRDs + Gateway Inference Extension CRDs) will eventually be extracted into a standalone charm for use across the Juju ecosystem. When that charm exists, `envoy-controller-k8s` will consume it via a relation instead of installing the CRDs itself. **Not in scope for the initial implementation.**

---

## Implementation Course Correction & Revised Architecture

> **This section supersedes the original design above wherever they conflict — it is the authoritative as-built/as-planned record.** Everything before this point captures the **original design** as first specified (single control-plane pod with two controllers, certs from a `tls-certificates` relation). During implementation on a live cluster, two load-bearing assumptions of that design broke. The original text is retained deliberately as a record of the reasoning and the dead ends; this section documents the **walls that were hit** and the **revised architecture** adopted in response.
>
> **Legend:** ✅ **Built & verified live** · ✅ **Revised design (agreed direction, not yet implemented)**

### Wall 1 — Two controllers cannot share one pod ✅ (diagnosed)

The original design runs the Envoy Gateway controller and the AI Gateway controller as two Pebble containers in **one pod**. Both are `controller-runtime` applications that bind their manager metrics on **`:8080`** by default, and containers in a single Kubernetes pod share one network namespace — so the second process to start dies with `listen tcp :8080: bind: address already in use`.

This is **not configurable away**: controller-runtime defaults `Metrics.BindAddress` to `:8080` (only the literal `"0"` disables it) and reads **no env override**; Envoy Gateway (verified through **v1.8.1**) hardcodes `nil` metrics options in its production `New()` entrypoint (`internal/provider/kubernetes/kubernetes.go` — `New()` calls `newProvider(..., nil, ...)`; only its unit test passes `BindAddress: "0"`); AI Gateway **v0.6.0** never sets `ctrl.Options.Metrics` (none of its flags reach the manager metrics listener). Neither exposes a flag/config/CRD/env to move or disable manager metrics. A secondary `:9443` clash (EG topology-injector webhook vs. AI ExtProc webhook) is independently avoidable, but `:8080` blocks regardless.

The only single-pod fix is to **fork/patch a controller image** (e.g. set `Metrics.BindAddress: "0"` at build time — viable since we build our own rocks, but it carries a per-version rebase burden, costs that controller's metrics, and still leaves `:9443`, dual leader-election, and shared-restart fragility).

#### Resolution: split into two charms ✅

Run each controller in its **own pod** as its **own charm** — the topology upstream Helm itself uses (two Deployments). This eliminates the entire co-location conflict class (not just `:8080`), requires no image fork, stays on the upstream-tested path, and gives the two control planes independent lifecycle, scaling, and upgrade cadence.

- **`envoy-controller-k8s`** — the Envoy Gateway control plane (this charm). Ships as a plain Envoy Gateway operator.
- **`envoy-ai-controller-k8s`** *(new)* — the AI Gateway controller in its own pod.

The original `enable-ai-gateway` config boolean is **removed**; AI is enabled by **relating** the AI charm to the controller charm (see *The EG ↔ AI relation* below) — the relation *is* the on/off switch.

### Wall 2 — The `tls-certificates` cert path failed ✅ (fixed)

The original design sources the xDS-server cert (and the AI webhook cert) from a `tls-certificates` relation and **eliminates upstream's `certgen`**, reusing one relation cert for both. This failed on the live cluster for two independent reasons:

- **Failure 1 — no `envoy-gateway` Service → Gateway never reaches `Programmed=True`.** Envoy Gateway hardcodes the proxy bootstrap to dial xDS/wasm at `envoy-gateway.<namespace>.svc` on ports `18000`/`18002` — the Service name its own Helm chart creates. There is **no override**. The Juju app Service is named after the charm (`envoy-controller-k8s`), so no `envoy-gateway` Service exists; the proxy's DNS lookup returns nothing and Envoy logs `no healthy upstream`. The Gateway stays `Programmed=False` (`NoResources`).
- **Failure 2 — cert-trust mismatch (`CERTIFICATE_VERIFY_FAILED`).** Envoy Gateway provisions the proxy's trust chain itself from its own self-signed **certgen CA** (`CN=envoy-gateway`): proxies receive a client cert + CA bundle via the `envoy` Secret and validate the xDS server cert **against the certgen CA**. A `tls-certificates` relation cert is signed by a *different* CA (e.g. `self-signed-certificates`), so the proxy's mTLS handshake fails with `unable to get local issuer certificate`. There is no point where both halves of the mTLS chain can share the relation CA without re-implementing certgen.

#### Resolution: keep certgen, drop the relation ✅

- **Keep `certgen`, remove `tls-certificates`.** The charm runs upstream's `envoy-gateway certgen` (in the gateway container) to mint the control-plane Secrets under one self-signed CA. The cert served from `/certs` is read from the certgen-issued **`envoy-gateway`** Secret — signed by the same CA the proxies already trust, so both halves of the mTLS chain share one CA by construction. certgen is **idempotent** (no `--overwrite`, so values are stable across reconciles/scaled units) and run with `--disable-topology-injector`.
- **Charm-managed `envoy-gateway` Service.** The charm reconciles (SSA via KRM) a `Service` named **`envoy-gateway`** in the model namespace, selecting the controller pods (`app.kubernetes.io/name: envoy-controller-k8s`), exposing `18000` (xDS) and `18002` (wasm). This is the name the proxy bootstrap dials, so DNS resolves and the upstream is healthy.
- **Result (verified live):** one certgen CA spans control + data plane; proxy connects over mTLS; Gateway reaches `Programmed=True` (control plane `active`, proxy pods `2/2`, no `CERTIFICATE_VERIFY_FAILED`).

### Revised Architecture: Two Charms ✅

#### Charm A — `envoy-controller-k8s` (Envoy Gateway control plane) ✅

Plain Envoy Gateway operator: installs Gateway API CRDs + the `gateway.envoyproxy.io` control-plane CRD group + the stable GIE `InferencePool`, runs the Envoy Gateway controller, owns certgen and the `envoy-gateway` Service, and manages the default `EnvoyProxy` resource. **No `tls-certificates` relation.** No AI controller, no AI CRDs, no ExtProc webhook in this charm.

#### Charm B — `envoy-ai-controller-k8s` (AI Gateway control plane) ✅ *(new)*

The AI Gateway controller in its own pod. Owns:
- the **`aigateway.envoyproxy.io` CRDs** (6: `AIGatewayRoute`, `AIServiceBackend`, `BackendSecurityPolicy`, `MCPRoute`, `GatewayConfig`, `QuotaPolicy`);
- the **ExtProc sidecar-injector `MutatingWebhookConfiguration`** and **its serving cert** — this hop is **apiserver → AI-controller webhook**, entirely internal to the AI side, so the cert is self-contained in this charm (self-signed in-charm, or via its own `tls-certificates` relation). It does **not** cross the EG↔AI relation and does **not** use EG's certgen;
- injecting the ExtProc sidecar into Envoy Proxy pods (proxy ↔ ExtProc is **intra-pod localhost** — no cross-pod cert).

#### The EG ↔ AI relation ✅

A relation between the two charms is **required**, not just a convenience gate: Envoy Gateway must be *configured* to call the AI controller via EG's **Extension Server protocol** (gRPC) to fine-tune xDS. EG's config must carry `extensionManager.service.fqdn = <ai-controller-svc>.<ns>.svc.cluster.local`, `port: 1063`, the `xdsTranslator` hooks, `extensionManager.backendResources: [{group: inference.networking.k8s.io, kind: InferencePool, version: v1}]` (mirrors the upstream `inference-pool` addon values so EG accepts `InferencePool` as an HTTPRoute `backendRef` and delegates its xDS translation to the extension server), and `extensionApis.enableBackend: true` / `enableEnvoyPatchPolicy: true`. EG cannot know the AI controller's service address until related — hence the relation.

- **AI charm → EG charm** (required payload): AI extension-server FQDN + port `1063`, and the signal to enable the extensionManager hooks + Backend API.
- **EG charm → AI charm** (lighter): `controllerName`/GatewayClass + namespace + a readiness signal, so the AI charm can gate itself.
- **The relation is the AI on/off switch** (replaces `enable-ai-gateway`): unrelated → EG runs plain; relate → EG writes `extensionManager` and AI comes alive; unrelate → EG reverts to plain. Without the relation the AI controller has nothing to fine-tune, so it is inert by construction.
- **Caveat:** Envoy Gateway reads its `EnvoyGateway` config at startup and does **not** hot-reload it, so the EG charm's relation-changed handler must rewrite the config and **restart the EG Pebble service**.

#### Certificate ownership (three hops) ✅

| Hop | Direction | Trust source | Owner |
|---|---|---|---|
| Control-plane xDS mTLS | EG controller ↔ Envoy Proxy | certgen CA (`envoy`/`envoy-gateway` Secrets) | **`envoy-controller-k8s`** (certgen) ✅ |
| ExtProc admission webhook | kube-apiserver → AI webhook (`:9443`) | AI charm's own cert; `caBundle` set by AI charm | **`envoy-ai-controller-k8s`** (self-managed) |
| Extension Server gRPC | EG controller → AI controller (`:1063`) | **plaintext by default** (no TLS block in upstream's required EG values) — no cert needed; optional later hardening would carry the AI server caBundle over the relation | — |

ExtProc ↔ proxy is localhost inside the proxy pod (no cert). Splitting cleanly separates the two cert domains the single charm had conflated: **EG charm → certgen**; **AI charm → its webhook cert**.

#### CRD ownership split ✅

- **`envoy-controller-k8s`** owns: Gateway API CRDs + `gateway.envoyproxy.io` control-plane group (8) + stable GIE `InferencePool`.
- **`envoy-ai-controller-k8s`** owns: `aigateway.envoyproxy.io` CRDs (6).

Each group is cluster-scoped; the **single-owner-per-cluster** constraint (see [Scaling Behavior](#scaling-behavior)) applies independently to each charm.

### As-Built Corrections (apply regardless of the split) ✅

Factual corrections to the original design discovered during implementation:

- **Versions & images.** Envoy Gateway **v1.7.0**, AI Gateway **v0.6.0**. The AI controller image is `docker.io/envoyproxy/ai-gateway-controller` — the originally specced `envoyproxy/ai-gateway` does **not** exist on Docker Hub (caused `ImagePullBackOff`). The two control planes must be **version-coherent**: AIGW v0.6.0 → EG v1.7.0; AIGW v0.7.0 / v1.0.0 → EG v1.8.1. Bundled CRDs must be regenerated to match whichever pair is pinned.
- **Envoy Gateway control-plane CRD group.** `gateway-helm` also installs EG's own `gateway.envoyproxy.io` group (8 CRDs: `EnvoyProxy`, `ClientTrafficPolicy`, `BackendTrafficPolicy`, `SecurityPolicy`, `EnvoyPatchPolicy`, `EnvoyExtensionPolicy`, `Backend`, `HTTPRouteFilter`). Since the charm installs CRDs itself, it must **vendor this group too** (applied unconditionally; `EnvoyProxy` must be `Established` before controllers start). Total CRD count ≈ **31** with AI.
- **AI CRD storage version.** As of v0.6.0 the core AI types serve **`v1beta1`** as storage version (v1alpha1 retained, served, non-storage); the controller's field indexing requires the `v1beta1` resources to be registered or it exits at startup (`no matches for aigateway.envoyproxy.io/v1beta1`).
- **`ENVOY_GATEWAY_NAMESPACE`.** Must point at the Juju **model namespace** (Helm injects it via the downward API). Left unset it defaults to `envoy-gateway-system`, which the charm never creates → controller and certgen fail on `namespaces "envoy-gateway-system" not found`.
- **`/certs`.** EG hardcodes this path for xDS-server TLS; the charm serves the certgen `envoy-gateway` Secret here (cert/key/CA). Without it `envoy-gateway` exits at startup (`open /certs/tls.crt: no such file or directory`).
- **Health checks.** EG exposes its controller-runtime health probe on HTTP **`:8081`** (`/healthz`, `/readyz`) — *not* a metrics port. The AI controller exposes only a **gRPC** health service on `:1063`; since Pebble has no gRPC check, use a **TCP** check on `:1063`.
- **`caBundle` encoding.** Kubernetes `caBundle` is a `[]byte` field, so it must be **base64-encoded** PEM (raw PEM fails with `illegal base64 data at input byte 0`).
- **ExtProc image pin.** Pass `--extProcImage docker.io/envoyproxy/ai-gateway-extproc:v<AI version>` to the AI controller so it never falls back to the upstream `:latest` default.
- **`EnvoyProxy` naming.** The default `EnvoyProxy` is named after the controller's Juju application; the ingress charm's `GatewayClass.spec.parametersRef` references it by that name (part of the cross-charm contract).
- **Cleanup on remove.** App-scoped resources (the `envoy-gateway` Service; the ExtProc webhook on the AI charm) are deleted **only on last-unit removal** (`planned_units == 0`), left in place on scale-down. CRDs are always left in place (removing them cascade-deletes cluster-wide custom resources).
- **CRD bundling.** Bundled CRD YAML lives under `src/crds/` (packed with `src/`), subdivided `gateway-api/`, `envoy-gateway/`, `gie/`, `ai-gateway/`.
- **Control-plane metrics need scrape, not OTLP.** EG's OTLP telemetry pipeline only exports what its binary chooses to push (xDS/config sync); it does **not** cover the kubebuilder metrics served on `:19001/metrics` (`controller_runtime_*`, `workqueue_*`, `certwatcher_*`, `controller_runtime_webhook_*`, `rest_client_*`, `go_*`). The controller-health dashboard needs those, so the charm adds a `metrics-endpoint` (`prometheus_scrape`) provider advertising `*:19001` and ships alert rules on that relation. `otlp` and `metrics-endpoint` are complementary — both must be related for full control-plane observability.
- **Data-plane metrics need per-Gateway identity, routed through OTLP resource attributes.** The Juju topology stats tags on the default `EnvoyProxy` (`juju_model`, `juju_application`, …) are app-scoped, so N Gateways under one controller produce identical series signatures and Prometheus silently collapses them into one indistinguishable stream. Envoy's `stats_config.stats_tags.fixed_value` accepts only literal strings — no `%ENV(...)%`, no `$(VAR)`, no runtime substitution — so per-pod identity cannot travel through that field. Envoy never substitutes anything in `fixed_value` — but it never needs to: envoy-gateway hands the bootstrap to Envoy as a `--config-yaml` container *argument*, and the **kubelet** expands `$(VAR)` in args against the container's env at pod start (the same mechanism EG itself uses for `$(ENVOY_SERVICE_ZONE)`). So the charm adds `{tag_name: gateway_name, fixed_value: $(ENVOY_GATEWAY_NAME)}` (and namespace) to the stats_tags patches, and lifts the `gateway.envoyproxy.io/owning-gateway-{name,namespace}` pod labels to exactly those env vars via the downward API in `EnvoyProxy.spec.provider.kubernetes.envoyDeployment.container.env`. The identity then flows as plain metric labels end-to-end, like the Juju topology tags. Two rejected alternatives: (a) OTLP *resource* attributes (sink `resourceAttributes`, or the `environment` resource detector) — the COS otelcol charm's prometheusremotewrite exporter has no `resource_to_telemetry_conversion`, so resource attributes never become Prometheus labels; (b) bootstrap JSON patches under `/stats_sinks` — EG's legacy jsonpb bootstrap validation rejects any patch touching the sink's `typed_config` (`Any JSON doesn't have '@type'`). `pod_name` is intentionally not added: cardinality would scale linearly with replicas without answering a question we can't already answer per-Gateway.

---

## Substrate

**Kubernetes charm(s)** — Ops framework, deployed on a Juju Kubernetes model.

---

## Installation Approach

The charm uses **Pebble + lightkube** (Option C) with `--trust` and `tls-certificates` relation:

| Concern | Mechanism |
|---|---|
| Controller processes | Pebble workload containers (one per controller) |
| Controller config files | `container.push()` via Pebble |
| TLS certs | `tls-certificates` relation → `container.push()` |
| RBAC | Eliminated by trust (`cluster-admin`) |
| CRDs (~23) | KRM `reconcile()` (server-side apply) from bundled YAML |
| ExtProc MutatingWebhookConfiguration | KRM `reconcile()` (server-side apply; CA from `tls-certificates` relation) |
| Default `EnvoyProxy` (OTLP sink + Juju-topology stats tags) | KRM `reconcile()` (server-side apply; endpoint from `otlp` relation) |
| Envoy Proxy pods, Services, xDS | Created automatically by the Envoy Gateway controller at runtime |
| ExtProc sidecar injection | Handled by the webhook + AI Gateway controller at runtime |
| ExtProc config Secrets | Created automatically by the AI Gateway controller at runtime |

The charm does **not** use Helm at runtime. All upstream Helm chart complexity (RBAC, certgen, ConfigMaps) is replaced by Juju-native mechanisms.

---

## Charm Configuration

### Config Options (v1)

| Config Key | Type | Default | Description |
|---|---|---|---|
| `log-level` | string enum: `debug`, `info`, `warn`, `error` | `info` | Logging level for both Envoy Gateway and AI Gateway controllers |
| `enable-ai-gateway` | boolean | `false` | Enables/disables AI Gateway features (see below) |
| `gateway-namespace-mode` | boolean | `false` | Selects Envoy Gateway's Kubernetes deploy mode — where the Envoy Proxy data plane is created (see below) |

### `enable-ai-gateway` Behavior

| State | Effect |
|---|---|
| `true` | Installs AI Gateway CRDs, runs AI Gateway controller container, configures extension manager in Envoy Gateway config, creates ExtProc MutatingWebhookConfiguration. Full AI Gateway functionality. |
| `false` (default) | Only runs Envoy Gateway controller with standard Gateway API + GIE support. No AI CRDs, no AI Gateway controller container, no extension manager config, no ExtProc webhook. Plain Envoy Gateway operator for general-purpose ingress. **Destructive when toggled from `true` → `false`:** removing the AI Gateway CRDs cascade-deletes all AI Gateway custom resources cluster-wide (`AIGatewayRoute`, `AIServiceBackend`, `BackendSecurityPolicy`, `MCPRoute`, `GatewayConfig`). Only disable AI Gateway when no AI Gateway custom resources are in use. |

### `gateway-namespace-mode` Behavior

Sets the Envoy Gateway controller-config field `provider.kubernetes.deploy.type`, which decides **where the controller provisions the Envoy Proxy data plane** (Deployment, Service, ServiceAccount, ConfigMap). It is the *only* charm-side knob for the mode — everything else the mode needs is handled by the controller at runtime (verified live against Envoy Gateway v1.7.0).

| State | `deploy.type` | Effect |
|---|---|---|
| `false` (default) | `ControllerNamespace` | Every proxy is created in **this controller's namespace**, regardless of where its Gateway lives. Control-plane↔proxy auth is **mTLS** (proxies mount the certgen `envoy` client-cert Secret). |
| `true` | `GatewayNamespace` | Each proxy is created in **its Gateway's own namespace** (e.g. the ingress charm's model), giving stronger cross-tenant isolation and letting the Gateway's LoadBalancer address be discovered locally. Control-plane↔proxy auth shifts to **server-side TLS + a projected service-account-token (JWT)**: the controller copies the CA (`ca.crt` from the controller-namespace `envoy` Secret) into a ConfigMap in each Gateway namespace and mounts a projected SA token (audience `envoy-gateway.<controller-ns>.svc.<dns-domain>`) into each proxy pod. |

**certgen is mode-agnostic.** `envoy-gateway certgen` reads no config file and has no `--config-path`; it always mints the same four control-plane Secrets (`envoy`, `envoy-gateway`, `envoy-rate-limit`, `envoy-oidc-hmac`) in the controller namespace from `ENVOY_GATEWAY_NAMESPACE`. So switching modes needs **no** change to the certgen step, the `CERTGEN_SECRETS` guard, or the reconcile order.

**Restart on toggle.** Envoy Gateway does not hot-reload its config, so the mode string is stamped into the layer config-hash (`_construct_gateway_layer`); a `config-changed` alters the hash and `replan()` restarts the controller to adopt the new mode.

**RBAC.** GatewayNamespace mode needs the controller to create/manage data-plane resources across arbitrary namespaces plus `tokenreviews`. Juju `--trust` (cluster-admin) already covers this — no extra ClusterRole manifests are shipped (unlike the upstream Helm chart, which adds a dedicated `cluster-infra-manager` ClusterRole).

**Incompatible with merged-gateways** (the charm does not set `mergeGateways`). Toggling relocates where *new* proxies are created; the controller re-provisions existing proxies in the new location.

### Internally Computed (not exposed)

| Setting | Derivation |
|---|---|
| Extension manager FQDN | `<self.app.name>.<self.model.name>.svc.cluster.local` — both controllers are in the same pod |
| TLS cert SANs | DNS SANs `<app>.<model>.svc.cluster.local`, `<app>.<model>.svc`, `<app>.<model>`, `<app>` — covers both the webhook Service name (port 9443) and the Extension Server FQDN (port 1063) |
| Proxy stats tags | Fixed `EnvoyProxy` stats tags `juju_model`, `juju_model_uuid`, `juju_application`, `juju_charm` (from `self.model`/`self.app`) — stamped onto all Envoy Proxy metrics (no `juju_unit`) |
| Upstream versions | Baked into the charm revision (Gateway API v1.4.1, GIE v1.3.0, Envoy Gateway v1.6.3, AI Gateway v0.5.0) |
| Controller name | Always `gateway.envoyproxy.io/gatewayclass-controller` |
| Extension APIs | Always `enableEnvoyPatchPolicy: true`, `enableBackend: true` |

### Future Config Candidates (not in v1)

| Config Key | When | Why |
|---|---|---|
| `watch-namespaces` | Multi-tenant support | Restrict which namespaces the controller watches |
| `enable-topology-injector` | Zone-aware routing | Optional MutatingWebhookConfiguration for zone info injection |
| `telemetry-*` | Observability relation | Metrics/tracing config when relating to Prometheus/Grafana charms |
| `rate-limit-*` | Redis relation | Global rate limiting config when relating to a Redis charm |

---

## Charm Lifecycle — Reconciler Pattern

The charm uses a single idempotent `_reconcile()` method invoked from **every** hook/event. Each call evaluates the full desired state and converges toward it. No hook-specific logic.

### Reconciler Flow

```
_reconcile():
  1. Check preconditions
     - Is the charm trusted? (cluster-admin SA exists)
     - Are Pebble containers connected?
     - Is the tls-certificates relation established and certs available?
     → If any precondition unmet: set appropriate waiting/blocked status, return

  2. Apply CRDs
     - Always apply Gateway API CRDs (~17)
     - Always apply GIE CRDs (1: `InferencePool`, stable `inference.networking.k8s.io` group only)
     - If enable-ai-gateway: apply AI Gateway CRDs (5)
     - If not enable-ai-gateway: remove AI Gateway CRDs if present (destructive — cascade-deletes AI custom resources cluster-wide)

  3. Push config files
     - Generate Envoy Gateway config YAML (log-level, extension manager FQDN if AI enabled, control-plane OTLP metrics sink from the `otlp` relation if related)
     - Push to Envoy Gateway container via Pebble
     - If enable-ai-gateway: generate + push AI Gateway controller config
     - Apply the default `EnvoyProxy` resource (via KRM): data-plane OTLP metrics sink from the `otlp` relation (if related) + fixed Juju-topology stats tags (`juju_model`, `juju_model_uuid`, `juju_application`, `juju_charm`)

  4. Push TLS certs
     - Write CA cert, server cert, server key to both containers via Pebble

  5. Manage MutatingWebhookConfiguration
     - If enable-ai-gateway: ensure ExtProc sidecar injector webhook exists, targeting the charm's Service via `clientConfig.service` (port 9443), with `caBundle` set to the issuing CA from the tls-certificates relation
     - If not enable-ai-gateway: ensure webhook is removed

  6. Manage Pebble services
     - Ensure Envoy Gateway controller service is running with correct config
     - If enable-ai-gateway: ensure AI Gateway controller service is running
     - If not enable-ai-gateway: ensure AI Gateway controller service is stopped
     - Each controller service defines Pebble health checks (HTTP `/healthz` liveness, `/readyz` readiness) with `on-check-failure: restart` for automatic recovery from crash loops

  7. Evaluate controller health
     - Read Pebble check status for each running controller
     - If a check is failing, collect a `waiting` status (transient — Pebble auto-restarts; resolves on its own, so not `blocked`)

  8. Set final status
     - Evaluate collected statuses and set the most important one (see Status Resolution below)```

### Status Resolution

Status is set during `_reconcile()`. **Halting conditions** (precondition failures in step 1) set status and return immediately — no further work is attempted. **Non-halting conditions** are collected in a status accumulator object throughout execution. At the end of `_reconcile()`, the most important status is selected using this priority order:

1. `blocked` (highest — user action required)
2. `waiting` (external condition pending)
3. `maintenance` (active work in progress)
4. `active` (lowest — everything healthy)

If multiple statuses of the same priority are collected, the **first one added** wins (it's likely the most relevant). If no non-halting conditions were collected, the charm sets `active` with no message.

### Events That Trigger Reconcile

`_reconcile()` is the charm's single convergence point and is observed on **every Juju event the charm receives** — there is no hook-specific logic, so the charm does not maintain a hand-curated allowlist of "reconcile-triggering" events (such a list inevitably drifts as relations are added). The events below are **illustrative, not exhaustive**:

- `install`
- `config-changed`
- `upgrade-charm`
- `pebble-ready` (both containers)
- All relation events for every relation the charm has — `certificates`, `otlp`, `grafana-dashboard` (`-relation-joined`, `-changed`, `-broken`, `-departed`)
- `secret-changed` / `secret-expired` — **required for TLS cert rotation:** `tls-certificates` (v4) delivers renewed certs via Juju secrets, not via `certificates-relation-changed`. Without observing these, the charm would never re-push a rotated cert and the webhook/Extension-Server cert would silently expire.
- `update-status` — periodic safety net so a unit that missed an event still re-converges
- `collect-status` — sets the final unit status (see Status Resolution)
- `remove` (cleanup webhook only — CRDs are left in place, Juju handles pod/namespace teardown)

### Status Model

| Status | Condition | Message |
|---|---|---|
| `blocked` | Trust not granted | `Trust not granted — run 'juju trust envoy-controller-k8s'` |
| `blocked` | TLS certificates relation not established | `Missing relation: certificates` |
| `waiting` | Pebble containers not yet connected | `Waiting for Pebble (envoy-gateway container)` |
| `waiting` | TLS certs requested but not yet available | `Waiting for TLS certificates` |
| `waiting` | A controller Pebble health check is failing (e.g., crash-looping) | `Waiting for envoy-gateway controller to become healthy` |
| `maintenance` | Applying CRDs | `Applying CRDs` |
| `maintenance` | Pushing config | `Configuring envoy-gateway controller` |
| `maintenance` | Creating/updating webhook | `Creating ExtProc webhook` |
| `maintenance` | Starting/restarting controllers | `Starting controllers` |
| `active` | All preconditions met, controllers running | *(no message)* |
| `error` | Unexpected failure (exception raised) | *(Juju captures the exception)* |

### Status Rules

- **`blocked`**: Used **only** when a specific user action is required to proceed. The message must tell the user exactly what to do. When used as a halting condition (step 1), reconciliation stops. When collected as non-halting, it takes highest priority in final status resolution.
- **`waiting`**: Used when the charm is waiting for an external condition that will resolve on its own (Pebble readiness, cert issuance).
- **`maintenance`**: Used during active reconciliation steps. Since `_reconcile()` runs synchronously, these are transient — the final status at hook end will be the resolved status from the accumulator.
- **`active`**: No message. The charm is healthy and fully operational.
- **`error`**: The charm raises an exception when it encounters an unexpected failure and does not know how to recover. Juju automatically sets error status and captures the exception. Not collected — exceptions bypass the accumulator.

### Idempotency Guarantees

- CRD apply is idempotent (lightkube `apply` is a server-side apply / create-or-update)
- Config push + Pebble replan is idempotent (Pebble only restarts if the plan actually changed)
- Webhook create/update is idempotent (lightkube `apply`)
- Safe to call from any event in any order

### Cleanup on Remove

- Remove the ExtProc MutatingWebhookConfiguration (if it exists)
- **CRDs are left in place** — removing CRDs would cascade-delete all custom resources cluster-wide (Gateways, HTTPRoutes, AIGatewayRoutes, etc.), which is destructive and may affect other applications
- Juju handles pod, StatefulSet, Service, and namespace teardown

---

## Container Images

### v1: Upstream Images

| Container | Image |
|---|---|
| Envoy Gateway controller | `docker.io/envoyproxy/gateway:v1.6.3` |
| AI Gateway controller | `docker.io/envoyproxy/ai-gateway:v0.5.0` |

Upstream images are well-maintained, multi-arch, and published to Docker Hub.

### Future: Rockcraft Rocks

Container images will be repackaged as Ubuntu-based OCI rocks via rockcraft. This is a single-line change in `metadata.yaml` per container — no charm code changes required.

---

## Scaling Behavior

The charm supports scaling via `juju scale-application envoy-controller-k8s N`.

### How It Works

- Juju scales the StatefulSet to N replicas → N pods, each running both controller containers.
- **Envoy Gateway controller** uses built-in Kubernetes Lease-based leader election. One instance actively reconciles; others are hot standbys. Automatic failover if the leader pod dies.
- **AI Gateway controller** also uses `controller-runtime` leader election. Same behavior.
- **Webhook serving** is stateless — the K8s Service load-balances across all pods. Multiple pods improve webhook availability.
- **Extension Server (gRPC)** is stateless — any pod can serve requests.
- **All units run `_reconcile()` identically** — every unit applies CRDs, manages the webhook, pushes config, and starts controllers. Cluster-scoped writes go through **KRM**, which makes concurrent multi-unit execution safe by construction:
  - **Concurrent applies** use **server-side apply** with a shared, **app-scoped `field_manager`** (not per-unit). SSA is conflict-free across co-managers sharing a field manager, so N units applying the same ~23 CRDs + 1 webhook converge without `409 Conflict`.
  - **Concurrent deletes** (e.g., the AI Gateway CRD removal on `enable-ai-gateway: false`) are **unconditional** (no `resourceVersion` precondition) and run with `ignore_missing=True`, so a peer that already deleted the object yields a `404` that KRM swallows — no race, no error.
- **No Juju leadership gating** — all units behave identically. KRM's SSA + label-based reconcile + `ignore_missing` removes the need for leader-only coordination of cluster-scoped writes. This simplifies the model and avoids edge cases where the Juju leader is unhealthy but non-leader units are fine.
- **K8s API failures are not masked** — any non-404 error KRM raises (`K8sApiError` for transport/unreachable-API failures, or `RuntimeError` aggregating delete failures) propagates out of `_reconcile()`. These are treated as legitimate failures: the unit goes to **`error`** state (per the Status Model) so the operator sees them, rather than being silently downgraded to `waiting`. Only the expected `404`-on-delete case is swallowed (by KRM's `ignore_missing`).

### Controller Leader vs Juju Leader

The Envoy Gateway and AI Gateway controller leaders may run on **different pods**. This is fine — they communicate via the K8s Service FQDN, not localhost. Juju leadership is not involved in controller leader election.

### CRD Ownership Constraint (single owner per cluster)

The CRDs managed by this charm are **cluster-scoped** and global. KRM stamps **app-scoped ownership labels** on every managed resource, so units of the *same* application coordinate cleanly (shared label selector + shared SSA field manager). However, those labels identify *this app's* resources only — they do **not** coordinate across *separate* applications. For v1, therefore, **only one `envoy-controller-k8s` application per Kubernetes cluster** should manage them. Deploying a second instance (in another model, or at a different revision) is unsupported: each would carry its own label set yet both would apply the same cluster-scoped CRDs, and an older revision could downgrade schemas a newer one depends on. The charm does not stamp finalizers or version annotations on CRDs, nor coordinate between distinct applications. Multi-owner coordination and version-skew protection are deferred to the future `gateway-api-crds` charm (see Charm Architecture), which will own the CRDs once per cluster and be consumed via relation.

---

## Testing Strategy

### Unit Tests

- Framework: `pytest` with `ops.testing` (state-transition testing, formerly Scenario)
- Mock Pebble, lightkube, and `tls-certificates` interactions
- Test cases:
  - Reconciler sets `blocked` when trust is missing
  - Reconciler sets `waiting` when Pebble not connected
  - Reconciler sets `waiting` when TLS certs not available
  - Reconciler applies CRDs and starts controllers when all preconditions met
  - Config generation produces correct Envoy Gateway YAML (with/without AI features)
  - `enable-ai-gateway: false` omits extension manager config, stops AI controller, removes webhook
  - `log-level` changes propagate to controller config
  - Status messages match the defined status model
  - Webhook resource includes correct CA bundle from TLS relation
  - Webhook `clientConfig` uses `service` (not `url`) targeting the charm's Service on port 9443
  - TLS cert request includes the pinned DNS SAN set (`<app>.<model>.svc.cluster.local`, `<app>.<model>.svc`, `<app>.<model>`, `<app>`)
  - Controller health: collect-status reports `waiting` (not `active`) when a Pebble health check is failing
  - Ingress route conflict: two route specs with the same path resolve to `blocked` with a conflict message (pure logic, no live cluster needed)

### Integration Tests

- Framework: `jubilant` with `pytest-jubilant` v2 and `pytest-bdd` for BDD-style feature files
- Feature files live in each charm's own `tests/integration/features/` directory (in the target monorepo, each charm has its own directory; this section lists both charms' suites)

#### `envoy-controller-k8s` integration tests

| Feature File | Scope |
|---|---|
| `deploy.feature` | Deploy with/without trust, status verification. No `tls-certificates` relation: the charm mints its own control-plane certs via Envoy Gateway certgen. |
| `crds.feature` | Gateway API and GIE CRDs installed; AI Gateway CRDs are **not** installed by this charm (they belong to `envoy-ai-controller-k8s`) |
| `controllers.feature` | `envoy-gateway` Pebble service running |
| `extension_server.feature` | `envoy-extension-server` requirer: extensionManager wired + controller identity published when related to the AI controller; absent otherwise. Requires `envoy-ai-controller-k8s`, so step-defs are deferred to the cross-charm suite. |
| `scaling.feature` | Scale up/down, all units active, Gateway API CRDs consistent |
| `otlp.feature` | OTLP sink configured/removed on relate/break with opentelemetry-collector; alert rules published in relation databag |
| `grafana_dashboard.feature` | Dashboard JSON shipped when related to grafana-k8s |

#### `envoy-ingress-k8s` integration tests

| Feature File | Scope |
|---|---|
| `deploy.feature` | Deploy with/without trust, waiting when controller unavailable, active when controller available |
| `gateway_resources.feature` | GatewayClass accepted, Gateway programmed, Envoy Proxy pod provisioned (both charms deployed) |
| `ingress.feature` | HTTPRoute created/removed on ingress relate/break, multiple relations, route conflict detection |
| `certificates.feature` | HTTP by default, HTTPS listener when tls-certificates related |
| `gateway_metadata.feature` | Gateway name/namespace/addresses published when related |
| `forward_auth.feature` | SecurityPolicy created/removed on forward-auth relate/break |

### Out of Scope

End-to-end traffic flow tests (AI routing, ExtProc processing, model inference) are handled separately and are not part of the charm test suite.

### Testing Notes

- **Shared controller fixture**: every `envoy-ingress-k8s` feature requires a running `envoy-controller-k8s` stack (the ingress charm creates real `Gateway`/`HTTPRoute` resources that need a live GatewayClass controller). To avoid redeploying per scenario, the controller stack (controller + `self-signed-certificates`) is deployed **once per feature file** via a **module-scoped** fixture; Background steps are idempotent "ensure deployed" steps. Module scoping (rather than session scoping) isolates cluster-scoped state between feature files, so a scenario in one file that mutates shared cluster-scoped state (e.g., `crds.feature` toggling `enable-ai-gateway` off, which removes the AI Gateway CRDs) cannot leak that state into another file. Within a single feature file, scenarios are assumed to run top-to-bottom in authored order, so any destructive/state-mutating scenario (e.g., "AI CRDs removed when disabled") is authored **last**. Pure logic (databag parsing, HTTPRoute generation, conflict detection) is covered by unit tests rather than live-cluster scenarios.
- **Composite "active" step**: the step `the envoy-controller-k8s charm is deployed with trust` deploys the charm with `--trust`; the charm reaches `active` on its own once its CRDs are established and it has minted its own control-plane certs via Envoy Gateway certgen (no `tls-certificates` relation is required). Step definitions surface the underlying Juju status on failure to aid diagnosis.
- **Cross-model conflict scenario**: `ingress.feature`'s conflicting-routes scenario uses cross-model relations (CMR) — a single ingress charm related to two requirers in different models. This is the most complex/slow scenario and should be tagged so it can be run independently of the fast suite. The conflict-detection *logic* is also covered by a unit test so a CMR/infra flake never leaves it untested.
- **Upgrade tests deferred**: the sequential upgrade logic (version-jump blocking, CRD `Established` ordering) requires multiple published charm revisions to exercise end-to-end. Integration upgrade scenarios are deferred until multiple revisions are published; the version-jump and CRD-ordering logic is unit-tested in the meantime.

---

## Relations

### Charm 1: `envoy-controller-k8s` (control plane)

| Relation Name | Interface | Direction | Purpose |
|---|---|---|---|
| `certificates` | `tls-certificates` | requires | TLS certs for webhook server + Extension Server |
| `otlp` | `otlp` | requires | OTLP endpoint for controller **and** Envoy Proxy metrics; publishes alert/recording rules into the relation databag via the `otlp` lib's `RuleStore`. Envoy Gateway pushes proxy metrics via the default `EnvoyProxy`'s `telemetry.metrics.sinks` OpenTelemetry sink, configured with the endpoint received from the OTLP relation. Proxy metrics carry Juju topology labels (see Proxy Metrics Topology), so the lib's automatic topology injection into alert rules matches both control-plane and data-plane series. |
| `grafana-dashboard` | `grafana_dashboard` | provides | Ships bundled Grafana dashboard JSON for both Envoy Gateway controller health and Envoy Proxy data plane metrics (connections, latency, error rates). Dashboards use standard Juju topology variables (`$juju_model`, `$juju_application`) — proxy metrics are tagged with this app's Juju topology via the default `EnvoyProxy` stats tags — with `gateway_name`/`gateway_namespace` available for per-gateway breakdown. |

### Charm 2: `envoy-ingress-k8s` (gateway resources)

| Relation Name | Interface | Direction | Purpose |
|---|---|---|---|
| `ingress` | `ingress` | provides | Provides ingress for requiring charms. Receives app name, model, port, and `strip_prefix` from the requirer; creates an HTTPRoute through the Gateway to expose the application at `/{model}-{app}`. When `strip_prefix` is set, the route carries a `URLRewrite` (`ReplacePrefixMatch: /`) filter so the backend receives the unprefixed path. Routes attach per-listener via `parentRef.sectionName`: without TLS the backend route attaches to the HTTP listener; with TLS the backend route attaches to the HTTPS listener and a second route on the HTTP listener redirects plaintext to HTTPS (301). Each HTTPRoute is created in the requirer's namespace (co-located with its backend Service) so the same-namespace `backendRef` needs no `ReferenceGrant` for cross-model requirers; the route attaches to the Gateway via its `allowedRoutes: {from: All}` listeners. Returns the ingress URL. |
| `certificates` | `tls-certificates` | requires | TLS certs for Gateway HTTPS listeners |
| `gateway-metadata` | `gateway-metadata` | provides | Publishes Gateway info (gateway name, namespace, listener addresses, ports) for downstream consumers |
| `forward-auth` | `forward-auth` | requires | Connects to an external auth provider charm. The provider advertises a `decisions_address` URL (not a Service name), so the charm parses its host/port into an Envoy Gateway `Backend` CR (`spec.endpoints[].fqdn`) and creates a `SecurityPolicy` whose `extAuth.http.backendRefs[0]` references that `Backend` (`kind: Backend`), carrying the URL path when present. The `Backend` and `SecurityPolicy` are created together and removed when the relation breaks. |

---

## Juju Actions

**None for v1.** Everything is declarative via config and relations. Diagnostics are available through `juju status`, `juju debug-log`, and `kubectl`.

---

## Cross-Charm Discovery

Charm 2 needs to know that Charm 1 (Envoy Gateway controller) is running before creating Gateway/HTTPRoute resources. For v1, there is **no cross-charm relation**. Instead, the shared `GatewayClass` (owned by Charm 1) is the discovery signal:

- The `GatewayClass` name is a hardcoded constant (`envoy`) on **both** charms — the cross-charm contract. Charm 1 creates it; Charm 2 only references it.
- During `_reconcile()`, Charm 2 uses **lightkube** to **read** `GatewayClass/envoy` and check for an `Accepted=True` condition — indicating the controller is running and has claimed it.
- If the GatewayClass is not yet accepted (or absent), Charm 2 sets `waiting` status: `Waiting for GatewayClass controller to become available`.
- If the GatewayClass is accepted, Charm 2 proceeds to create/update its `Gateway` with `gatewayClassName: envoy`.
- Charm 2 sets **no** `parametersRef` and does **not** create a `GatewayClass` or `EnvoyProxy`. The `parametersRef` → `EnvoyProxy` lives on Charm 1's `GatewayClass` (Charm 1 owns the `EnvoyProxy` and the `otlp` relation that populates its OTLP sink), so **all** proxies across all ingress deployments inherit one shared config. Charm 2 has no `otlp` relation and therefore nothing to contribute to proxy config.

This avoids a cross-charm relation while still giving the user clear status feedback, and works uniformly for one controller serving many ingresses across multiple models (and multiple ingresses in a single model).

---

## Upgrade Strategy

### Sequential Upgrades Only

The charm enforces **sequential minor version upgrades**. Each charm revision embeds the upstream component versions it ships (e.g., Envoy Gateway v1.6.3, AI Gateway v0.5.0). On `upgrade-charm`, the reconciler compares the previously running version (persisted in stored state) against the new revision's version.

If the upgrade skips one or more minor versions, the charm sets `blocked` status:

> `Unsupported version jump: Envoy Gateway v1.6.3 → v1.8.0. Please upgrade to revision <N> (v1.7.x) first.`

The charm does **not** apply CRDs, push config, or start controllers until the version constraint is satisfied.

### CRD Upgrade Ordering

CRDs are always applied (step 2 of `_reconcile()`) **before** controllers are started (step 6). After applying CRDs, the charm uses lightkube to poll each CRD's status until the `Established` condition is `True`, confirming the API server is ready to serve the new resource versions. Only then does it proceed to push config and start controllers.

### Rollback

**Downgrades are not supported.** CRDs cannot be safely downgraded (removing fields cascade-deletes stored data). If an upgrade fails:

- The charm will be in `blocked` or `error` status with a diagnostic message.
- The user should investigate via `juju debug-log` and `kubectl`.
- If the new controller is incompatible, the user can `juju refresh` back to the previous charm revision. The reconciler will restart the old controller binaries, but CRDs will remain at the newer version. This is generally safe since CRDs are additive, but is not guaranteed by upstream.
- Users should test upgrades in a staging environment first.

### Data Plane Continuity

During controller restarts (upgrade or otherwise), existing Envoy Proxy pods **continue serving traffic** with their last-known xDS configuration. Envoy uses eventual consistency — proxies cache their config and only update when the controller reconnects and pushes new xDS snapshots. There is no data plane downtime during controller upgrades.

### Upgrade Testing

Integration test scenarios for upgrades (sequential happy path, version-jump blocking, CRD `Established` ordering) are **deferred until multiple charm revisions are published**, since they require real intermediate revisions to exercise end-to-end. The version-jump and CRD-ordering logic is covered by unit tests in the meantime.

---

## Directory Layout

```
envoy-controller-k8s/
├── charmcraft.yaml          # Charm metadata, containers, resources, config, relations
├── pyproject.toml           # Project metadata, runtime + dev dependencies, tool config
├── uv.lock                  # Locked dependency versions (managed by uv)
├── src/
│   ├── charm.py             # Main charm class, _reconcile()
│   └── grafana_dashboards/  # Bundled dashboard JSON files
├── lib/                     # Charm libs (tls-certificates, grafana-dashboard, etc.)
├── templates/               # Envoy Gateway config templates
├── crds/                    # Bundled CRD YAML files
│   ├── gateway-api/
│   ├── gie/
│   └── envoy-gateway/
├── tests/
│   ├── unit/
│   └── integration/
│       └── features/        # pytest-bdd .feature files
└── tox.ini                  # Test runner config, delegates to uv for env management
```

- **`pyproject.toml`** — single source of truth for runtime and dev dependencies. No `requirements.txt`.
- **`uv`** — used for dependency resolution, locking (`uv.lock`), and virtual environment management. Fast, deterministic installs.
- **`tox.ini`** — defines test environments (`unit`, `integration`, `lint`, `fmt`). Each environment uses `uv` to install dependencies from the lock file.

- **CRD YAML files** are bundled in `crds/` and shipped with the charm revision. No runtime downloads.
- **Config templates** in `templates/` — used to generate controller config YAML with charm-specific values (log-level, extension manager FQDN, OTLP sink endpoint, etc.).
- **Single `charm.py`** — all charm logic in one file. Split into modules only if complexity warrants it.

---

## Discussion Points

Open topics to revisit in future iterations are tracked as GitHub issues:

- [#107 — Replace lightkube GatewayClass probe with a controller↔ingress relation](https://github.com/canonical/service-mesh/issues/107)
- [#108 — Verify Charmhub retention guarantees before relying on sequential upgrades](https://github.com/canonical/service-mesh/issues/108)
- [#109 — Expose supported API versions to client charms over relation data](https://github.com/canonical/service-mesh/issues/109)
- [#110 — Gate `extensionApis` behind the extension-server relation for least privilege](https://github.com/canonical/service-mesh/issues/110)
- [#111 — Control-plane certificate rotation via a `tls-certificates` relation](https://github.com/canonical/service-mesh/issues/111)
- [#112 — Enforce sequential minor-version upgrades on `upgrade-charm`](https://github.com/canonical/service-mesh/issues/112)
- [#113 — Whether to support multiple / coexisting Envoy Gateway controllers per cluster](https://github.com/canonical/service-mesh/issues/113)

### Single cluster-wide controller (current behaviour — under discussion in [#113](https://github.com/canonical/service-mesh/issues/113))

The charm currently assumes exactly one `envoy-controller-k8s` per cluster, owning the single cluster-scoped `envoy` GatewayClass that all ingress charms reference by that constant name (no controller↔ingress relation). A second controller — or a non-Juju install (Helm/kubectl) — that finds an existing `envoy` GatewayClass it does not own goes `BlockedStatus` (`Existing 'envoy' GatewayClass; see logs`) and refuses to touch the class, rather than silently fighting over the singleton. Ownership is read off the object itself: KRM stamps `app.kubernetes.io/instance=<model>-<app>` on resources it manages, so a class carrying our stamp is ours, and one without it (or with another app's) is foreign — no ownership bookkeeping needed (`_foreign_gateway_class_owner`). The alternative under consideration is coexistence via a unique per-deployment `controllerName` + configurable class name shared with the ingress; this makes the class name part of the cross-charm contract (config or relation) and breaks the zero-config `"envoy"` discovery. Note: the guard covers the GatewayClass, not a second Envoy Gateway *control plane* installed out-of-band (that collides on control-plane ports, a separate concern).
