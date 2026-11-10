# istio-k8s Requirements

The istio-k8s charm deploys and manages the Istio service mesh control plane (ambient profile) on a Kubernetes cluster on behalf of Juju. This document lists the requirements the charm must satisfy, derived from its source (`src/charm.py`, `src/istioctl.py`, `src/cni_ownership.py`, `src/config.py`, `charmcraft.yaml`).

## High-level requirements

- **R1.** The charm must install the Istio control plane.
  - **R1.1.** The charm must install the istiod (pilot) component.
  - **R1.2.** The charm must install the Istio CNI component.
  - **R1.3.** The charm must install the ztunnel component.
  - **R1.4.** The charm must install the control plane in Istio's ambient mode (`values.profile=ambient`).
  - **R1.5.** The charm must generate the control plane manifests with the `istioctl manifest generate` command, selecting the `pilot`, `cni` and `ztunnel` components.
  - **R1.6.** The charm must install the control plane into the Juju model's namespace (Istio's root namespace is the model name).
  - **R1.7.** The charm must use Canonical Ubuntu rock images for istiod, CNI and ztunnel instead of upstream Istio images.
    - **R1.7.1.** The charm must disable the default distroless image tag suffix that istioctl appends (`values.global.variant=""`).
  - **R1.8.** The charm must adapt the generated istiod and ztunnel workloads to run the Pebble-based rock images.
    - **R1.8.1.** The charm must mount a writable emptyDir volume at `/run/pebble` for istiod and ztunnel, because these workloads enforce a read-only root filesystem.
    - **R1.8.2.** The charm must set the `PEBBLE` and `PEBBLE_COPY_ONCE` environment variables so Pebble's runtime directory points to the writable mount and its baked-in layer config is copied on first start.
    - **R1.8.3.** The charm must strip the container args from ztunnel, because the `proxy ztunnel` args injected by istioctl are misinterpreted by Pebble as subcommands.
  - **R1.9.** The charm must enable CNI iptables reconciliation on startup so existing pods are re-enrolled in the mesh after CNI restarts (`values.cni.ambient.reconcileIptablesOnStartup=true`).
  - **R1.10.** The charm must exclude all outbound IP ranges from sidecar injection (`excludeOutboundIPRanges=0.0.0.0/0`) as a workaround for CNI incompatibility with application init containers.
  - **R1.11.** The charm must enable Envoy access logging to stdout (`meshConfig.accessLogFile=/dev/stdout`).

- **R2.** The charm must install the Istio CRDs.
  - **R2.1.** The charm must generate the Istio CRDs from istioctl's `base` component.
  - **R2.2.** The charm must not deploy the ServiceAccount that istioctl includes in the `base` component manifest.

- **R3.** The charm must install the Gateway API CRDs.
  - **R3.1.** The charm must deploy the Gateway API CRDs from the bundled manifest (`src/manifests/gateway-apis-crds.yaml`).
  - **R3.2.** The charm must also deploy the Gateway API ValidatingAdmissionPolicies and their bindings from the bundled manifest.

- **R4.** The charm must continuously reconcile its Kubernetes resources.
  - **R4.1.** The charm must re-run reconciliation on the config-changed, start, update-status, leader-elected, metrics-proxy Pebble-ready, peer relation changed/departed, certificate relation update/removal, and the istio-ingress-config, istio-metadata and workload-tracing relation events.
  - **R4.2.** The charm must apply the desired resources with server-side apply, labelling every resource it manages with an application/instance label and a per-scope label.
  - **R4.3.** The charm must delete any deployed resources carrying its labels that are no longer in the desired state (drift removal).
  - **R4.4.** The charm must only manage the Kubernetes resource types it declares per scope (control plane, Istio CRDs, Gateway API CRDs, authorization policies), so it never touches unrelated resources.
  - **R4.5.** The charm must only reconcile from the leader unit.
  - **R4.6.** The charm must not reconcile the control plane when the application has zero planned units, and must rely on the remove hook for cleanup in that case.

- **R5.** The charm must scale istiod with the application.
  - **R5.1.** The charm must override istiod's HorizontalPodAutoscaler so that its min and max replicas equal the charm's planned unit count.
  - **R5.2.** The charm must rescale the HPA whenever the unit count changes (observed via the peers relation and update-status).

- **R6.** The charm must enforce single Istio CNI ownership per cluster.
  - **R6.1.** The charm must claim the shared cluster-scoped `ClusterRoleBinding/istio-cni` before installing or reconciling any resource, using the binding's creation as arbitration so it never overwrites an existing claim.
  - **R6.2.** The charm must only accept ownership of a claim that carries this installation's labels and grants access to the expected CNI ClusterRole and ServiceAccount.
  - **R6.3.** The charm must block reconciliation while another recognized istio-k8s installation owns the claim, and report the owning installation and its namespace.
  - **R6.4.** The charm must block reconciliation and ask for manual investigation if the existing claim is not recognizable as an istio-k8s claim.
  - **R6.5.** The charm must report waiting status while the claim is absent or being deleted, and must retry claiming automatically (via update-status reconciliation).

- **R7.** The charm must support its configuration options.
  - **R7.1.** The charm must validate its configuration before using it.
  - **R7.2.** The charm must pass the `platform` option to Istio's `values.global.platform` when set, so Istio can adapt to platform-specific Kubernetes setups.
  - **R7.3.** The charm must pass the `cni-bin-dir` option to `values.cni.cniBinDir` when set.
  - **R7.4.** The charm must pass the `cni-conf-dir` option to `values.cni.cniConfDir` when set.
  - **R7.5.** The charm must set `PILOT_AUTO_ALLOW_WAYPOINT_POLICY=true` when `auto-allow-waypoint-policy` is true, so Istio automatically creates L4 authorization policies allowing waypoints to reach their workloads.
  - **R7.6.** The charm must apply a default-deny posture when `hardened-mode` is true.
    - **R7.6.1.** The charm must create a global allow-nothing AuthorizationPolicy for ztunnel in the Istio namespace.
    - **R7.6.2.** The charm must create an allow-nothing AuthorizationPolicy targeting the `istio-waypoint` GatewayClass.
    - **R7.6.3.** The charm must remove those AuthorizationPolicies when `hardened-mode` is false.
    - **R7.6.4.** The charm must manage these AuthorizationPolicies with its own labels and resource scope, so reconciliation removes any that are no longer desired.

- **R8.** The charm must report its status.
  - **R8.1.** Non-leader units must report standby.
  - **R8.2.** The charm must report waiting status while the istio-cni-node DaemonSet is not ready.
  - **R8.3.** The charm must report waiting status while the ztunnel DaemonSet is not ready.
  - **R8.4.** The charm must report waiting status while the istiod Deployment is not ready.
  - **R8.5.** The charm must report active status when all control plane components are ready.
  - **R8.6.** The charm must report the CNI-ownership status before workload readiness (waiting while unclaimed, blocked when owned elsewhere or unrecognized).
  - **R8.7.** The charm must set the unit's workload version to the Istio control plane version reported by `istioctl version`, or clear it if unavailable.

- **R9.** The charm must remove its resources when the application is removed.
  - **R9.1.** The charm must delete all resources it deployed (control plane, Istio CRDs, Gateway API CRDs, authorization policies), except the shared CNI ClusterRoleBinding.
  - **R9.2.** The charm must leave the CNI ClusterRoleBinding in place if another installation owns it.
  - **R9.3.** The charm must, when it owns the CNI claim, keep ownership until all control plane pods have terminated (bounded wait), so CNI pods can clean up node-local state, and then delete the ClusterRoleBinding.

- **R10.** The charm must expose control plane metrics.
  - **R10.1.** The charm must run a metrics broadcast proxy Pebble service in the charm's own container, configured to select the control plane pods by their telemetry label.
  - **R10.2.** The charm must label the istiod, ztunnel and istio-cni-node pod templates with unique telemetry labels so each mesh application's metrics are isolated from other applications' (label keys stay within the Kubernetes 63-character limit and include a hash of the model/application names to avoid collisions).
  - **R10.3.** The charm must provide a `metrics-endpoint` relation (prometheus_scrape) advertising a scrape job for the metrics proxy on port 15090.

- **R11.** The charm must provide Prometheus alert rules.
  - **R11.1.** The charm must forward its infrastructure alert rules (ztunnel connected, CNI ready, root cert expiry, pilot conflicts, etc.) over the `metrics-endpoint` relation.
  - **R11.2.** The charm must forward its workload alert rules (proxy queue time, XDS push latency, etc.) over the `metrics-endpoint` relation.

- **R12.** The charm must provide Grafana dashboards.
  - **R12.1.** The charm must provide a `grafana-dashboard` relation shipping the bundled dashboards: control-plane, mesh, performance, services, workloads, and ztunnel.

- **R13.** The charm must send its own trace spans.
  - **R13.1.** The charm must send its own Python trace spans to the tracing backend related over `charm-tracing` (OTLP HTTP, no CA certificate because Istio does TLS its own way).

- **R14.** The charm must configure workload tracing.
  - **R14.1.** The charm must obtain the tracing backend's OTLP gRPC endpoint from the `workload-tracing` relation.
  - **R14.2.** The charm must register an `otel-tracing` extension provider in the Istio mesh config pointing at that endpoint.
  - **R14.3.** The charm must enable mesh tracing, select `otel-tracing` as the default tracing provider, and set tracing sampling to 100%.
  - **R14.4.** The charm must drop the tracing provider and mesh tracing settings when the `workload-tracing` relation is removed or its endpoint disappears.

- **R15.** The charm must integrate external authorizers for ingress traffic.
  - **R15.1.** The charm must publish a unique external authorizer provider name (`ext-authz-<application>`) back to each ready related ingress application over `istio-ingress-config`.
  - **R15.2.** The charm must read each related ingress application's external authorizer service configuration (service name, port, protocol, and header forwarding rules) from the `istio-ingress-config` relation.
  - **R15.3.** The charm must register an `envoyExtAuthzGrpc` or `envoyExtAuthzHttp` mesh config extension provider for each ready relation, matching the protocol and header rules the ingress application published.
  - **R15.4.** The charm must ignore fake external authorizer configuration that ingress charms publish as a cross-model relation-breaking workaround, and must treat it as no relation.
  - **R15.5.** The charm must re-reconcile providers when the `istio-ingress-config` relation changes or breaks, so removed authorizers drop out of the mesh config.

- **R16.** The charm must trust external Certificate Authorities for JWKS resolution.
  - **R16.1.** The charm must receive CA certificates over the `jwks-ca-cert` (certificate_transfer) relation.
  - **R16.2.** The charm must bundle the received CA certificates (sorted, deterministic) and configure istiod's `jwksResolverExtraRootCA` with the bundle via an IstioOperator overlay, so istiod can fetch JWKS keys from endpoints serving self-signed certificates.
  - **R16.3.** The charm must re-reconcile the bundle when certificates are added, updated or removed.

- **R17.** The charm must publish Istio metadata to related applications.
  - **R17.1.** The charm must publish the mesh root namespace (the Juju model name) over the `istio-metadata` relation so related charms (e.g. beacon, Kiali) know how to interface with this Istio installation.

- **R18.** The charm must run only on supported platforms.
  - **R18.1.** The charm must assume a Kubernetes API endpoint and Juju >= 3.6.
  - **R18.2.** The charm must be deployed with cluster-scoped permissions (Juju `--trust`), since it manages cluster-scoped resources.

## Non-requirements (present in code, not a charm responsibility)

- `istioctl.py` also wraps `install`, `precheck`, `upgrade` and `uninstall` subcommands; the charm never calls them (installation goes through manifest generation plus the resource manager, and removal through the resource manager's delete). They are library capability, not charm requirements.
