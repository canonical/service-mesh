# Istio proxy tracing: POC findings and productionization specification

**Status:** Experimental POC completed; production changes proposed, not implemented.
**Evidence period:** 7-8 September 2026.
**Scope:** Canonical Istio charms with a minimal charmed Grafana/Tempo backend.

## 1. Summary

The POC demonstrates useful application-traffic and authorization visibility from
Istio proxies without adding a tracing SDK or exporter to the applications.
Envoy exports spans directly to Tempo; Grafana searches and displays them.

The initial off-mesh Tempo integration worked through the existing
`istio-k8s:workload-tracing` relation, without modifying Istio, beacon or Tempo
source. Moving the backend onto the mesh also worked, but required explicit
authorization workarounds and a preventive tracing exclusion.

The resulting system is a working demo, not a production-ready deployment.
Its principal gaps are automatic policy generation for real exporter identities,
supported receiver exclusions, dashboard delivery, sampling controls, storage
reliability and operational hardening.

### What "instrumentationless" means here

| Capability | What the POC established |
|---|---|
| Generate HTTP spans without an application SDK | Yes: an SDK-free client, without trace headers, produced an Envoy span |
| Export spans without an application exporter | Yes: the proxies exported OTLP directly |
| Connect spans across arbitrary unmodified applications | No: applications must propagate context between incoming and outgoing requests |
| Display a connected Bookinfo request | Yes: Bookinfo already contains instrumentation/context-forwarding code |
| Observe authorization failures | Yes for the exercised L7 denials; not every L4 rejection produces an HTTP span |
| Run the tracing backend on mesh | Yes for the minimal stack, with the documented workarounds |
| Support all of COS on mesh | Not established: Prometheus, Loki and other COS components were not deployed |

`ztunnel` provides ambient L4 transport and enforcement; it is not an Envoy HTTP
tracer. The ingress and waypoint Envoy proxies generate the inspected spans.
Matching `telemetry.sdk.name=envoy` distinguishes these from application or
charm-generated spans.

## 2. Deployment and traffic model

The POC uses one Canonical Kubernetes node, Juju controller `ck8s`, Kubernetes
context `kuma`, and three dedicated models/namespaces.

| Model | Applications | Role |
|---|---|---|
| `istio-system` | `istio-k8s`, `ingress` | Control plane, shared mesh components and ingress |
| `mesh-o11y-demo` | `beacon`, `productpage`, `details`, `reviews`, `ratings` | Application traffic and authorization demo |
| `o11y-poc` | `mesh-beacon`, `grafana`, `tempo`, `tempo-worker`, `seaweedfs` | Minimal on-mesh observability backend |

Logical traffic flow:

```text
Client -> Istio ingress -> productpage -> details
                                      -> reviews -> ratings

Ingress and application waypoint Envoy proxies
    -> OTLP/gRPC :4317 -> Tempo coordinator -> Tempo worker
                                               -> SeaweedFS S3 :8333

Browser -> Istio ingress -> Grafana
                              -> Tempo coordinator query API :3200
```

This is not a diagram of an identical waypoint hop on every connection.
In the inspected Bookinfo trace, ingress reached productpage directly, while
backend service calls traversed the application waypoint. The connected result
contained five spans across four services: two ingress spans, details, reviews
and ratings. No separate productpage waypoint span was observed.

The backend's own waypoint does not report spans. This prevents its processing
of OTLP traffic from recursively generating more traffic to the same receiver.

### Observed versions

| Application | Channel | Charm revision | Workload where recorded |
|---|---|---|---|
| `istio-k8s` | `dev/edge` | 73 | Istio 1.29.0 |
| `ingress` | `dev/edge` | 83 | Istio ingress |
| Application `beacon` | `dev/edge` | 85 | Istio waypoint |
| Backend `mesh-beacon` | `dev/edge` | 85 | Istio waypoint |
| `grafana` | `dev/edge` | 199 | Grafana 12.4.2 |
| `tempo` | `dev/edge` | 164 | Coordinator |
| `tempo-worker` | `dev/edge` | 122 | Tempo 2.10.3 |
| `seaweedfs` | `latest/edge` | 9 | SeaweedFS 3.97, source hotpatch |
| `productpage`, `details`, `reviews`, `ratings` | `latest/stable` | 5, 7, 5, 5 respectively | Reviews configured as `v2` |

These are historical pins, not recommended production channels. Charm revision
numbers are not monotonic across channels.

## 3. Native integration versus POC customization

| Surface | Native behavior | POC customization |
|---|---|---|
| Mesh tracing | `workload-tracing` supplies Tempo's receiver; istiod configures proxies | No tracing source patch |
| Bookinfo authorization | Service-mesh relations generate declared caller/path/method permissions | Relations and configuration enabled; initial artificial deny removed |
| Grafana ingress | Standard `ingress` relation supported by the newer Grafana charm | Old temporary HTTPRoute removed |
| Grafana -> Tempo | `grafana-source` provisions the datasource and supports authorization | Custom dashboard references migrated after datasource identity changed |
| Coordinator/worker mesh access | Coordinator library manages worker labels and internal policies | No direct worker-to-beacon relation added |
| Proxy -> on-mesh Tempo | Existing policy did not identify the real exporters correctly | Two narrow OTLP ALLOW policies |
| Tempo -> on-mesh S3 | SeaweedFS did not supply the necessary mesh authorization | One narrow S3 ALLOW policy |
| Backend proxy tracing | No receiver exclusion was present | One namespace `Telemetry` resource |
| Stored trace reads | S3 range-read throttling caused transient failures | One SeaweedFS charm-source command-line change |
| Trace dashboard | Istio already supplies metrics dashboards, not this POC trace dashboard | Authenticated Grafana API provisioning and frontend fixes |

There was **one deployed charm-source hotpatch**, to SeaweedFS. The on-mesh
workarounds are **four Kubernetes resources**: three authorization policies and
one Telemetry resource. Dashboard changes are Grafana configuration, not charm
source changes.

## 4. Authorization model and on-mesh findings

### 4.1 Application policies now come from relations

All four Bookinfo applications are related to their beacon:

```bash
juju integrate -m ck8s:mesh-o11y-demo productpage:service-mesh beacon:service-mesh
juju integrate -m ck8s:mesh-o11y-demo details:service-mesh beacon:service-mesh
juju integrate -m ck8s:mesh-o11y-demo reviews:service-mesh beacon:service-mesh
juju integrate -m ck8s:mesh-o11y-demo ratings:service-mesh beacon:service-mesh
juju config -m ck8s:mesh-o11y-demo beacon manage-authorization-policies=true
```

Namespace enrollment remains enabled with `model-on-mesh=true`.

| Caller | Destination | Declared permission on port 9080 |
|---|---|---|
| Productpage | Details | `GET /health`, `GET /details/*` |
| Productpage | Reviews | `GET /health`, `GET /reviews/*` |
| Productpage | Ratings | `GET /health`, `GET /ratings/*` |
| Reviews | Ratings | `GET /health`, `GET /ratings/*` |

Details also declares a peer L4 policy. Productpage's external ingress policy
remains owned by the ingress charm; there is no `website` relation generating an
additional beacon website policy.

These are ALLOW policies: unmatched requests to their selected targets are
rejected. This is not a claim that the entire cluster has default-deny coverage
or that every possible direct-pod bypass has been audited.

The initial manual policy, `o11y-poc-deny-details-99`, was deleted:

```bash
kubectl --context kuma delete authorizationpolicy \
  -n mesh-o11y-demo o11y-poc-deny-details-99
```

Consequently, `GET /details/99` from productpage now succeeds. Realistic denials
instead use undeclared paths, methods or callers: for example, productpage
posting to details, or details calling reviews without a corresponding relation.

### 4.2 The relation owner is not necessarily the exporter

`istio-k8s:workload-tracing` controls mesh tracing configuration, but istiod does
not send these workload spans. In this POC, the exporters are the ingress and
application waypoint proxies, with identities:

```text
cluster.local/ns/istio-system/sa/ingress-istio
cluster.local/ns/mesh-o11y-demo/sa/mesh-o11y-demo-beacon-waypoint
```

When backend authorization was enabled, the tracing relation produced a rule for
a synthetic cross-model identity:

```text
cluster.local/ns/o11y-poc/sa/remote-25b8fc017b3b4a3e80a45b494d683e72
```

That identity does not represent the actual exporters. Granting access to the
relation owner, or just correcting its namespace, is therefore insufficient.
The production interface needs to communicate the identities of the proxies
that send telemetry and reconcile permissions as those proxies are added,
removed or replaced.

Cross-model receiver discovery already worked before enrollment. The finding is
an **authorization/identity-model gap**, not missing cross-model trace export.

### 4.3 L4 and L7 policies protect different routes

A Service-target policy applies at the waypoint. A workload-selector policy
applies at L4. Routing through a service and connecting directly to a pod are
not interchangeable for authorization purposes.

For OTLP, the POC installed both policy forms, restricted to the two exporter
identities and port 4317. Export recovered after applying them. The necessity of
each policy independently was not isolated; production work must establish the
minimal rules for each supported route.

SeaweedFS advertised a headless per-unit S3 endpoint. Its ordinary ClusterIP
Service only exposed a placeholder port, not an S3 L7 listener. Tempo's object
reads therefore used a direct L4 route. Enrollment initially caused:

```text
Tempo query: HTTP 500, S3 bloom-object read failed with connection reset
ztunnel: connection closed due to policy rejection:
         allow policies exist, but none allowed
```

A selector policy authorizing Tempo identities on SeaweedFS port 8333 restored
storage access. Successful HBONE connections with authenticated worker/storage
identities were then observed.

### 4.4 Worker support is indirect

Tempo worker has no direct `service-mesh` endpoint. Its coordinator's
`coordinated_workers` library manages solution labels and coordinator/worker
authorization. A separate worker-to-beacon relation was not needed.

Those internal policies appeared when the coordinator mesh relation became
active, even while beacon's policy-management flag was false. The initial
enrollment phase was therefore **not a policy-free transport baseline**.

### 4.5 Receiver tracing requires an explicit exclusion

Without an exclusion, tracing a receiver request can generate a span whose
export creates another receiver request. The POC installed a preventive
namespace-scoped exclusion before enrollment; it did not deliberately trigger
a runaway feedback loop.

The exclusion disables backend **proxy** span reporting, including receiver
listeners. It does not turn off application/charm tracing inside Tempo, nor
tracing in the application namespace or external ingress.

This broad namespace exclusion sacrifices backend proxy visibility. Production
must define a supported receiver-exclusion mechanism or send backend
self-observability to an independent sink, rather than silently applying raw
YAML.

## 5. Exact live Kubernetes workarounds

These manifests record the applied POC configuration. Names, namespaces, service
accounts and ports are deployment-specific; do not apply them unchanged to
another environment.

They persist as Kubernetes objects, but are not generated by the charms and
will not automatically follow renamed applications or new exporter identities.

### 5.1 `backend-tracing-exclusion.yaml`

```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: o11y-poc-disable-proxy-tracing
  namespace: o11y-poc
  labels:
    app.kubernetes.io/part-of: mesh-o11y-poc
spec:
  tracing:
    - disableSpanReporting: true
```

### 5.2 `backend-storage-policy.yaml`

This grants only the listed identities access to the selected storage workload's
S3 port. It does not permit all traffic in the namespace.

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: o11y-poc-tempo-s3
  namespace: o11y-poc
  labels:
    app.kubernetes.io/part-of: mesh-o11y-poc
spec:
  action: ALLOW
  selector:
    matchLabels:
      app.kubernetes.io/name: seaweedfs
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/o11y-poc/sa/tempo-worker
              - cluster.local/ns/o11y-poc/sa/tempo
      to:
        - operation:
            ports: ["8333"]
```

### 5.3 `backend-exporter-policy.yaml`

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: o11y-poc-proxy-otlp-l4
  namespace: o11y-poc
  labels:
    app.kubernetes.io/part-of: mesh-o11y-poc
spec:
  action: ALLOW
  selector:
    matchLabels:
      app.kubernetes.io/name: tempo
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/istio-system/sa/ingress-istio
              - cluster.local/ns/mesh-o11y-demo/sa/mesh-o11y-demo-beacon-waypoint
      to:
        - operation:
            ports: ["4317"]
---
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: o11y-poc-proxy-otlp-service
  namespace: o11y-poc
  labels:
    app.kubernetes.io/part-of: mesh-o11y-poc
spec:
  action: ALLOW
  targetRefs:
    - group: ""
      kind: Service
      name: tempo
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/istio-system/sa/ingress-istio
              - cluster.local/ns/mesh-o11y-demo/sa/mesh-o11y-demo-beacon-waypoint
      to:
        - operation:
            ports: ["4317"]
```

### 5.4 Recorded enrollment sequence

The following records the trial, including its initially failing intermediate
states. It is not a zero-downtime production rollout recipe. Save the manifest
blocks above under the indicated filenames before using their apply commands.

```bash
kubectl --context kuma apply -f backend-tracing-exclusion.yaml

juju deploy -m ck8s:o11y-poc istio-beacon-k8s mesh-beacon \
  --channel dev/edge --revision 85 --trust \
  --config model-on-mesh=true \
  --config manage-authorization-policies=false

juju integrate -m ck8s:o11y-poc grafana:service-mesh mesh-beacon:service-mesh
juju integrate -m ck8s:o11y-poc tempo:service-mesh mesh-beacon:service-mesh
juju config -m ck8s:o11y-poc mesh-beacon manage-authorization-policies=true

kubectl --context kuma apply -f backend-storage-policy.yaml
kubectl --context kuma apply -f backend-exporter-policy.yaml
```

The final namespace labels are charm-managed:

```yaml
istio.io/dataplane-mode: ambient
istio.io/use-waypoint: o11y-poc-mesh-beacon-waypoint
```

Grafana-to-Tempo query authorization remains generated from the existing
`grafana-source` relation. Grafana ingress authorization remains generated by
the ingress charm.

## 6. Exact SeaweedFS source hotpatch

### Failure and cause

Before moving the backend on mesh, repeated stored-trace queries intermittently
failed with `unexpected EOF` while Tempo read Parquet data. For the same blocks,
SeaweedFS logged HTTP 429 responses on internal volume reads. A throttled
internal read truncated an already-started S3 response.

This was not evidence that stored objects needed deletion or Tempo data needed
resetting. Increasing the bounded volume download budget restored reads of
existing traces.

### Applied diff

Deployed file:

```text
/var/lib/juju/agents/unit-seaweedfs-0/charm/src/charm.py
```

```diff
--- a/src/charm.py
+++ b/src/charm.py
@@ -103,7 +103,8 @@ class SeaweedfsK8S(ops.CharmBase):
                             "-ip.bind=0.0.0.0 "
                             "-master.electionTimeout 1s "
                             "-master.volumeSizeLimitMB=1024 "
-                            "-volume.max=0"
+                            "-volume.max=0 "
+                            "-volume.concurrentDownloadLimitMB=512"
                         ),
                         "startup": "enabled",
                         "environment": {
```

SeaweedFS 3.97's default was 64 MB. The new value is a read-concurrency accounting
budget, **not a container memory limit**. Approximately 1073 MiB of pod memory
was observed during the earlier repeated-query exercise; 512 is not a universal
production sizing recommendation.

The patched source was copied into the charm container and reconciled:

```bash
kubectl --context kuma cp -n o11y-poc -c charm \
  seaweedfs-charm.py \
  seaweedfs-0:/var/lib/juju/agents/unit-seaweedfs-0/charm/src/charm.py

juju exec -m ck8s:o11y-poc --unit seaweedfs/0 -- \
  env JUJU_DISPATCH_PATH=hooks/config-changed ./dispatch
```

Here `seaweedfs-charm.py` means the saved revision-9 source with the diff applied,
not a file supplied by this repository. The original was backed up separately.

Patched source SHA256:

```text
7ee7273db40f7d491842b125b9565b47b7189fc118c81c19c9e2b9663a9d1180
```

Reconciliation retains the modified command, but a charm refresh/redeployment
can overwrite the hotpatch. SeaweedFS was deliberately excluded from the
`dev/edge` refresh. Production needs a supported storage implementation and a
validated configuration option or coordinated query-concurrency limit.

## 7. Dashboard changes and intended delivery

### Current POC ownership

The dashboard `istio-tracing-poc` was created through Grafana's authenticated
HTTP API and stored in its database. Its exported JSON and helper scripts are
POC artifacts. No tracing dashboard has been packaged into an Istio charm yet.

It contains an explanation panel, recent traces, authorization denials and a
selected-trace waterfall. Authentication remains enabled.

### 7.1 Waterfall query fix

The original target worked through Grafana's backend query API but did not
render through the frontend. For the tested Grafana 12.4 version, the saved
dashboard target must use `traceql`; the frontend recognizes a hexadecimal ID
and dispatches the backend trace-ID query.

```diff
- "queryType": "traceId",
+ "queryType": "traceql",
  "query": "${trace_id}"
```

Do not mechanically make this replacement in direct `/api/ds/query` requests:
the backend and saved frontend target are different interfaces.

### 7.2 Same-tab trace selection

Both trace tables received the following field override:

```json
{
  "matcher": {"id": "byName", "options": "Trace ID"},
  "properties": [
    {"id": "links", "value": null},
    {
      "id": "links",
      "value": [
        {
          "title": "Show in waterfall",
          "url": "/o11y-poc-grafana/d/istio-tracing-poc?${__url_time_range}&var-trace_id=${__value.raw}",
          "targetBlank": false
        }
      ]
    }
  ]
}
```

The explicit `null` clears inherited datasource links. Without it, Grafana
12.4 merged the new link with its Explore link instead of replacing it.
The matcher uses the displayed `Trace ID` field name.

### 7.3 Datasource migration after refresh

The Tempo coordinator refresh changed its provisioned datasource from a
unit-suffixed name to an application-level name:

| Before | After |
|---|---|
| Name ending in `_tempo_0` | Name ending in `_tempo` |
| UID `PB7E035C51F6A09E3` | UID `P666CAF0744CD7B9C` |

The custom dashboard retained the old UID and showed no data. Only its Tempo
panel/target datasource references were migrated; layout and user interaction
were preserved. Production dashboards must not embed either UID.

### 7.4 Updated denial query and empty-window behavior

After removing the artificial details-only deny, the denial table was broadened:

```traceql
{ resource.service.name =~ ".*mesh-o11y-demo.*" && span.http.status_code = "403" }
```

This is a POC-specific filter, not the proposed generic production query.

The dashboard uses a last-hour window, while Tempo was configured for 24-hour
retention. Yesterday's traffic can disappear from the table before it expires
from storage. A fixed selected trace can also expire independently of the
current search results. The demo default was refreshed manually after new
traffic; production must handle both cases explicitly.

### Proposed production delivery

`istio-k8s` should own the generic mesh request/security trace dashboard and
deliver it through its existing `grafana-dashboard` provider. Tempo should
continue owning backend-health dashboards.

Relevant existing implementation:

- `charms/istio-k8s/charmcraft.yaml`: dashboard relation declaration.
- `charms/istio-k8s/src/charm.py`: `GrafanaDashboardProvider`.
- `charms/istio-k8s/src/grafana_dashboards/`: existing bundled metrics dashboards.

The new dashboard must support a Tempo datasource selector, deployment/service
filters, status filtering and same-tab trace selection without fixed POC names.
Filters must use attributes actually present in Envoy spans; Juju topology
attributes must not be assumed just because the dashboard is charm-delivered.
Datasource templating and frontend behavior need coverage across supported
Grafana versions.

## 8. Other changes and temporary workarounds

| Change | Final disposition |
|---|---|
| Manual `GET /details/99` DENY | Removed; relation-derived authorization now supplies realistic denials |
| Temporary raw Grafana HTTPRoute | Removed after moving to a Grafana version with native standard `ingress` support |
| Grafana `2/stable` to `12.4/stable`, then `dev/edge` | Native ingress retained; no raw route needed |
| Istio/ingress/beacon/Grafana/Tempo `dev/edge` refreshes | Completed; Bookinfo and SeaweedFS excluded |
| Tempo workload upgrade from 2.8.2 to 2.10.3 | Required datasource-reference migration, not a tracing source patch |
| Initial Tempo startup port collision | Recovered by restarting `tempo-0`; no persistent source/configuration patch |
| Tempo compactor readiness delay after refresh | Recovered after ring stabilization; no patch |

No Cilium configuration change, application instrumentation change or
Istio/Tempo tracing source patch was made for this POC. Persistent storage was
not deleted or reset.

## 9. Observed outcomes and limits

| Scenario | Observed result |
|---|---|
| SDK-free single-service request | HTTP 200 with an Envoy-generated span |
| Connected Bookinfo ingress request | Five Envoy spans across four services |
| Relation-derived traffic simulation | 100 requests: 52 allowed, 48 denied; all 11 distinct scenarios retrieved by trace ID |
| Productpage -> details `GET /details/99` after manual-policy removal | HTTP 200 |
| Productpage -> details `POST /details/0` or `GET /admin` | HTTP 403, `RBAC: access denied` |
| Details -> reviews/ratings without a declared relation | HTTP 403 with waypoint spans |
| Unrelated productpage -> Tempo query API on 3200 | HTTP 403 |
| Unrelated productpage -> Tempo HTTP ingestion on 4318 | HTTP 403 |
| On-mesh backend after workarounds | Fresh export, retained reads, storage flushing and Grafana interaction worked |
| Backend waypoint tracing exclusion | HTTP connection-manager tracing configuration absent, including receiver listeners |

Representative historical evidence:

| Evidence | Trace ID |
|---|---|
| SDK-free request without supplied context | `5a71fd64851d4cc5204ce6d8b46ca191` |
| Relation-derived POST denial | `a83366bf084a4995bfe8be9d2dbb2736` |
| Undeclared details -> reviews caller | `40ccc06c2dd44da7b0461047d68bdba4` |
| Successful connected trace with backend on mesh | `5acc7e77abc44b3c8c77ceb019895da4` |
| Retained trace read after backend enrollment | `dcc424819263436b812e8243b616f3c0` |

These IDs document observations, not permanent fixtures: retention can remove
them. Saved evidence must accompany any longer-lived reproduction package.

The POC did not establish multi-node HA, recovery objectives, sustained load
capacity, complete direct-pod bypass prevention, multi-cluster support or full
COS compatibility. Host-originated requests are not sufficient authorization
evidence; the negative scenarios above used actual application pod identities.

## 10. Proposed production requirements and ownership

Ownership below is proposed, not an implementation commitment. Story IDs are
local specification identifiers, not existing Jira tickets.

| ID / priority | Proposed owner | Required outcome |
|---|---|---|
| OBS-01 / P1 | Istio dashboard provider | Relation-delivered generic trace dashboard; no fixed datasource, model or trace IDs |
| OBS-02 / P0 | Istio, beacon, tracing/mesh interfaces and Tempo | Discover actual exporter identities; reconcile least-privilege receiver policies across models and lifecycle events |
| OBS-03 / P0 | Tracing provider and mesh integration | Supported, durable receiver tracing exclusion with clear self-observability semantics |
| OBS-04 / P0 | Storage provider and coordinated-worker integration | Declare service/direct-unit storage access; remove handwritten S3 exception and deployed-source tuning |
| OBS-05 / P1 | Istio tracing configuration | Validated sampling and volume controls, with documented retention of errors/denials |
| OBS-06 / P0 | Backend/security operators and charms | Managed credentials, protected ingress/receivers, tenant boundaries and sensitive-data policy |
| OBS-07 / P0 | Backend deployment and operations | Supported resilient storage, capacity limits, backup/restore and availability design |
| OBS-08 / P1 | Cross-charm integration coverage | Off/on-mesh, refresh, scaling, removal, failure and browser-interaction coverage |

P0 items are release blockers for the intended production profile, not claims
that a particular HA topology or capacity target has already been selected.

### Sampling, privacy and failure visibility

The current Istio implementation hardcodes sampling at `100.0` in
`_workload_tracing_provider()` in `charms/istio-k8s/src/charm.py`.
Production must expose a bounded, validated setting and define override
precedence for namespace/workload policies.

Ordinary head sampling cannot guarantee retaining every failed request: the
sampling decision can precede the eventual failure. If error-aware tail
sampling is required, evaluate an OTel collector with bounded buffering,
backpressure and explicit failure semantics. A collector is not required merely
to export Envoy spans and should not be added without a requirement.

Captured URLs, headers and attributes must be inventoried for secrets and
personal data. Define allowlists/redaction, retention and access controls.
Mesh identity does not replace end-user or tenant authorization. Mesh-protected
paths also do not eliminate the need for TLS on external ingress or other
unprotected segments.

### Storage, availability and operations

The community/testing SeaweedFS deployment uses permissive internal credentials
and a live source hotpatch; it is not a production storage recommendation.
Choose supported resilient storage and establish ingestion/query limits,
WAL/disk sizing, compaction behavior and backup/restore.

Availability requirements must determine replicas, failure domains, Tempo
deployment mode and Grafana's database architecture. A single-node POC cannot
prove an HA design. Do not assume a charm-channel rollback safely downgrades
Tempo data or Grafana's database.

Monitor export failures/drops, ingestion lag, query errors, storage throttling,
WAL/disk pressure, certificate expiry and waypoint availability. A dashboard
that depends on Tempo cannot independently report that the tracing pipeline is
dead. Existing metrics/alerting infrastructure can supply this without making a
full COS bundle mandatory for the feature.

## 11. Production acceptance criteria

| Area | Acceptance criterion |
|---|---|
| Native off-mesh export | A fresh SDK-free request produces retrievable proxy spans using only supported relations/configuration |
| Context propagation | A propagating multi-service app yields connected parentage; a non-propagating control does not imply automatic correlation |
| Native on-mesh export | Fresh and retained traces work without manually applied allow policies or Telemetry resources |
| Exporter lifecycle | Adding/removing models, waypoints and ingress instances updates access without stale or blanket permissions |
| Negative access | Unrelated workload identities cannot query/ingest/read storage; exercise both Service and direct-unit paths |
| Feedback prevention | Receiver traffic does not cause recursive proxy exports; exclusions survive refresh/reconciliation and have defined removal behavior |
| Storage lifecycle | Queries succeed after flushing/compaction and under agreed concurrency; recovery and retention are demonstrated |
| Dashboard lifecycle | Relation creation/removal, datasource recreation and upgrades preserve intended behavior without hardcoded UIDs |
| Dashboard UX | Browser-rendered waterfall, same-tab selection, empty windows and expired traces behave explicitly |
| Volume controls | Sampling/limits follow documented semantics; overload and exporter failure are observable |
| Security | TLS/identity rotation, credential handling, tenant isolation and captured-data policy meet the selected deployment profile |
| Recovery | Failure-domain, backup/restore and upgrade exercises meet agreed availability and data-loss objectives |

Numeric load targets, availability/data-loss objectives, tenancy requirements
and supported version combinations remain decisions to make before release.
They must not be inferred from the POC's traffic counts.

## 12. Safe rollback and reproduction notes

This document records changes; it does not authorize automatic teardown.
Rolling back the backend mesh trial should be a coordinated maintenance action.

1. Remove the Grafana/Tempo service-mesh relations and allow consumer labels and
   coordinator-owned internal policies to reconcile.
2. Set backend `mesh-beacon` to `model-on-mesh=false` and
   `manage-authorization-policies=false`. Confirm namespace and application
   enrollment labels are removed and off-mesh connectivity works.
3. Only then delete `o11y-poc-proxy-otlp-l4`,
   `o11y-poc-proxy-otlp-service`, `o11y-poc-tempo-s3` and
   `o11y-poc-disable-proxy-tracing`. Keep the receiver exclusion until backend
   mesh tracing is no longer possible.
4. Optionally remove the backend `mesh-beacon` application after confirming it
   has no remaining consumers. Preserve application beacon, Bookinfo policies,
   ingress routes, PVCs and unrelated models.

To undo the SeaweedFS hotpatch, restore the saved original revision-9 source and
dispatch `config-changed`; expect a storage-service restart and possible return
of the original read-throttling problem. Do not reset trace data.

Do not reapply the historical manual details denial or temporary Grafana route
unless intentionally restoring an older demo configuration.

Supporting scripts and raw evidence are session artifacts, not repository
dependencies: `replay-demo.sh`, `simulate-mesh-traffic.py`,
`check-fresh-trace.py`, `check-waterfall.mjs`, `dashboard.json`,
`automatic-auth-traffic.json`, `backend-on-mesh-resources.json` and
`backend-on-mesh-transport.txt`. Archive these separately if turning the POC into
a reproducible demonstration package. No passwords or storage keys belong in
that archive or this specification.
