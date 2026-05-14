# Service Mesh in Coordinated-Worker Charms

This document explains how service mesh integration works in charms that use the [`coordinated-workers`](https://github.com/canonical/cos-coordinated-workers) package (available from v2.1.0). It covers the architecture, policy management, and worker telemetry routing that enable secure, controlled communication in coordinator-worker deployments.

## Overview

Coordinated-worker charms (like Tempo, Loki, and Mimir) deploy a cluster of applications working together, consisting of:
- A **coordinator** charm that orchestrates the cluster and handles external communication
- One or more **worker** charms that perform distributed workload processing

When integrated with a service mesh, these charms require authorization policies for two distinct categories of communication:
1. **Cluster-internal policies**: Communication within the coordinated-worker cluster (coordinator ↔ workers, workers ↔ workers)
2. **External policies**: Communication between the coordinator and applications outside the cluster

The `coordinated-workers` package handles both categories automatically while allowing charm authors to define charm-specific external policies.

## Architecture

The service mesh integration in coordinated-worker charms uses two complementary approaches:

### ServiceMeshConsumer for external policies

The coordinator uses [`ServiceMeshConsumer`](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) to manage policies for **external** communication - that is, traffic between the coordinator and applications that relate to it via Juju relations. See [how traffic authorization works](./traffic-authorization.md) for details on `ServiceMeshConsumer`.

When the coordinator instantiates `ServiceMeshConsumer`, it provides:
- **Default policies**: Automatically created policies for common coordinator endpoints (e.g., allowing metrics scraping from the coordinator units)
- **Charm-specific policies**: Policies defined by the charm author for charm-specific relations (e.g., allowing API access from related applications)

These policies are passed to the beacon charm, which creates the corresponding authorization policy resources (such as Istio `AuthorizationPolicy` objects) in [managed mode](./managed-mode.md).

### PolicyResourceManager for cluster-internal policies

The coordinator uses [`PolicyResourceManager`](../how-to/manage-custom-policies-with-policyresourcemanager.md) to manage policies for **cluster-internal** communication - that is, traffic within the coordinated-worker cluster itself. This is necessary because:
- Cluster-internal communication patterns don't follow standard Juju relation-based patterns
- Worker-to-worker communication must be allowed dynamically as workers join/leave the cluster

The `PolicyResourceManager` creates and manages these policies directly in Kubernetes, independent of the beacon charm.

## Cluster-internal policies

The `coordinated-workers` package automatically generates three types of cluster-internal policies:

### 1. Coordinator to all cluster units

Allows the coordinator to communicate with any unit in the cluster (including itself and all workers):

```python
MeshPolicy(
    source_namespace=model_name,
    source_app_name=coordinator_app_name,
    target_namespace=model_name,
    target_selector_labels={"app.kubernetes.io/part-of": coordinator_app_name},
    target_type=PolicyTargetType.unit,
)
```

This policy uses label selectors to target all pods that are part of the coordinated-worker cluster, identified by the label `app.kubernetes.io/part-of: <coordinator-app-name>`.

### 2. Workers to all cluster units

For each worker application, allows that worker to communicate with any unit in the cluster:

```python
for worker_app in worker_apps:
    MeshPolicy(
        source_namespace=model_name,
        source_app_name=worker_app,
        target_namespace=model_name,
        target_selector_labels={"app.kubernetes.io/part-of": coordinator_app_name},
        target_type=PolicyTargetType.unit,
    )
```

This enables workers to communicate with each other and with the coordinator for distributed processing and coordination.

### 3. Workers to coordinator application

For each worker application, allows access to the coordinator's Kubernetes service:

```python
for worker_app in worker_apps:
    MeshPolicy(
        source_namespace=model_name,
        source_app_name=worker_app,
        target_namespace=model_name,
        target_app_name=coordinator_app_name,
        target_type=PolicyTargetType.app,
    )
```

This enables workers to communicate with the coordinator via its stable service address for consistent operations like configuration updates and status reporting.

### Why label selectors?

Cluster-internal policies use label selectors (`target_selector_labels`) instead of explicitly naming each unit because:
- **Dynamic membership**: Workers can be added or removed without updating policies
- **Automatic application**: New units automatically receive the correct labels and are immediately covered by existing policies
- **Simplified management**: A single policy covers all current and future units in the cluster

All coordinator and worker pods are labeled with `app.kubernetes.io/part-of: <coordinator-app-name>`, which the policies use to identify cluster members.

## Label reconciliation

A critical aspect of the coordinated-worker service mesh integration is the automatic reconciliation of Kubernetes labels on all pods in the cluster. These labels serve two purposes:

1. **Mesh enrollment**: Labels that identify pods as members of the service mesh (e.g., `istio.io/dataplane-mode: ambient`)
2. **Cluster membership**: Labels that identify pods as part of the coordinated-worker cluster (e.g., `app.kubernetes.io/part-of: <coordinator-app-name>`)

### How labels are reconciled on the coordinator

The coordinator reconciles labels on its own pods during each reconciliation cycle. It uses the `reconcile_charm_labels` function from the `service_mesh` library:

```python
reconcile_charm_labels(
    client=lightkube_client,
    app_name=coordinator_app_name,
    namespace=model_name,
    labels={
        "app.kubernetes.io/part-of": coordinator_app_name,
        # Plus any mesh labels from ServiceMeshConsumer
    }
)
```

The labels applied to coordinator pods include:
- **Cluster membership label**: `app.kubernetes.io/part-of: <coordinator-app-name>` - identifies this pod as part of the coordinated-worker cluster
- **Mesh labels**: Labels obtained from `ServiceMeshConsumer.labels()`, which come from the beacon charm and indicate the pod should be enrolled in the mesh (e.g., `istio.io/dataplane-mode: ambient` for Istio ambient mode)

```{important}
Mesh labels are added only when service mesh is enabled by integrating the coordinator with a beacon charm via `service-mesh` relation. But the cluster membership label is always applied, regardless of mesh status. It is a default coordinated-worker behavior.
```

### How labels are distributed to workers

Workers receive their labels from the coordinator via the `cluster` relation, then apply them to their own pods:

1. **Coordinator computes worker labels**: The coordinator determines what labels workers need:
   ```python
   worker_labels = {
       "app.kubernetes.io/part-of": coordinator_app_name,
       **mesh_labels,  # Labels from ServiceMeshConsumer (if mesh is enabled)
   }
   ```

2. **Coordinator publishes labels**: These labels are published in the `cluster` relation databag, making them available to all worker charms

3. **Workers receive labels**: Worker charms read the labels from the relation data

4. **Workers apply labels**: Each worker uses `reconcile_charm_labels` to apply the labels to its pods:
   ```python
   reconcile_charm_labels(
       client=lightkube_client,
       app_name=worker_app_name,
       namespace=model_name,
       labels=labels_from_coordinator
   )
   ```

This mechanism ensures that all pods in the coordinated-worker cluster have consistent labels without requiring any mesh-specific code in the worker charms themselves.

## External policies

External policies control access from applications **outside** the coordinated-worker cluster to the coordinator. These policies are defined by the charm author and passed to the `Coordinator` via the `charm_mesh_policies` parameter.

The `coordinated-workers` package combines these charm-specific policies with its own default policies:

### Default external policies

The package automatically creates policies for:
1. **Coordinator unit metrics**: Allows metrics scrapers to access the coordinator's nginx exporter
2. **Worker metrics proxy** (when telemetry proxying is enabled): Allows metrics scrapers to access worker metrics through the coordinator's proxy endpoint

### Charm-specific external policies

Charm authors define additional policies for their charm's specific relations. For example, a Tempo coordinator might define:

```python
charm_mesh_policies = [
    # Allow applications related via "tempo-api" to access API ports
    AppPolicy(
        relation="tempo-api",
        endpoints=[Endpoint(ports=[HTTP_PORT, GRPC_PORT])],
    ),
    # Allow Grafana to access the datasource API
    AppPolicy(
        relation="grafana-source",
        endpoints=[Endpoint(ports=[HTTP_PORT])],
    ),
]
```

See the [implementation guide](../how-to/add-service-mesh-support-to-coordinated-worker-charms.md) for details on defining these policies.

### Policy combination

The `coordinated-workers` package combines policies as follows:

```python
all_external_policies = default_policies + charm_mesh_policies
ServiceMeshConsumer(
    charm,
    policies=all_external_policies,
)
```

The `ServiceMeshConsumer` sends all these policies to the beacon charm, which creates the corresponding authorization resources.

## Worker telemetry routing

A critical aspect of service mesh integration in coordinated-worker charms is that **all worker telemetry must be routed through the coordinator**. This is not optional - it's a mandatory architectural requirement.

### What is worker telemetry routing?

Worker telemetry routing means that workers send their observability data (metrics, logs, traces, and remote-write data) to the coordinator, which then forwards it to the actual telemetry backends (Prometheus, Loki, Tempo, etc.).

Without telemetry routing:
```
Worker → Prometheus (direct)
Worker → Loki (direct)
```

With telemetry routing:
```
Worker → Coordinator (proxy) → Prometheus
Worker → Coordinator (proxy) → Loki
```

### Why is telemetry routing mandatory?

In a service mesh with [hardened mode](./hardened-mode.md) enabled, every network connection requires an explicit authorization policy. If workers communicated directly with telemetry backends, you would need:

1. **Per-worker policies to telemetry backends**: A separate policy for each worker unit to reach each telemetry backend unit
2. **Per-backend policies from workers**: Policies that dynamically update as workers or backends scale

For example, with 3 workers and 2 Prometheus units, you'd need 6 policies just for metrics. Add logs, traces, and remote-write, and the policy count explodes.

**With telemetry routing through the coordinator:**
- Workers only need policies to communicate with the coordinator (already covered by cluster-internal policies)
- The coordinator needs policies to communicate with telemetry backends (a fixed number based on the coordinator, not workers)
- Adding or removing workers doesn't require policy updates for external communication
- Telemetry backends only need to authorize the coordinator, not individual workers

### How routing is enabled

Charm authors enable telemetry routing by providing a `WorkerTelemetryProxyConfig` when instantiating the `Coordinator`:

```python
from coordinated_workers.worker_telemetry import WorkerTelemetryProxyConfig

coordinator = Coordinator(
    charm=self,
    worker_telemetry_proxy_config=WorkerTelemetryProxyConfig(
        http_port=TELEMETRY_PROXY_PORT,
        https_port=TELEMETRY_PROXY_PORT,
    ),
)
```

The `Coordinator` then:
1. Configures nginx to proxy telemetry requests from workers to backends
2. Provides workers with coordinator proxy URLs instead of direct backend URLs
3. Creates appropriate authorization policies for the proxy paths

See the [how-to guide](../how-to/add-service-mesh-support-to-coordinated-worker-charms.md) for implementation details.

## Policy reconciliation

The `coordinated-workers` package reconciles both types of policies during the coordinator's reconciliation cycle.

### External policy reconciliation

External policies are managed by `ServiceMeshConsumer`, which updates policies in the relation databag whenever relations change. The beacon charm then creates, updates, or deletes the corresponding authorization policy resources. This follows the standard [managed mode](./managed-mode.md) pattern for automatic policy generation.

### Cluster-internal policy reconciliation

Cluster-internal policies are managed by `PolicyResourceManager`. During reconciliation, the coordinator:
1. Queries the cluster topology to determine current worker applications
2. Generates the required set of cluster-internal policies
3. Compares with existing policies (identified by labels)
4. Creates, updates, or deletes policies to match the desired state

This reconciliation happens during every coordinator reconciliation cycle, ensuring policies stay synchronized with cluster membership.

## Worker charm mesh integration

Worker charms require minimal mesh-specific code because the coordinator handles all policy management. However, workers must:

1. **Include the `service_mesh` library** and its dependencies in their charm, even though they don't use it directly in code
2. **Trust the coordinator** for mesh configuration by accepting mesh labels that the coordinator applies to worker pods
3. **Send telemetry to coordinator proxy URLs** instead of direct backend URLs (provided automatically by the `Worker` class)

The `Worker` class from `coordinated-workers` automatically:
- Applies mesh labels provided by the coordinator
- Uses proxied telemetry URLs when available
- Handles the transition when service mesh is added or removed

See the [how-to guide](../how-to/add-service-mesh-support-to-coordinated-worker-charms.md) for setup instructions.

## Summary

Service mesh integration in coordinated-worker charms provides:

- **Automatic cluster-internal policy management** via `PolicyResourceManager`
- **Automatic label reconciliation** on coordinator and worker pods for mesh enrollment and cluster membership
- **Charm-specific external policy support** via `ServiceMeshConsumer`
- **Dynamic policy reconciliation** that adapts to cluster topology changes
- **Minimal worker charm changes** - most complexity handled by the `coordinated-workers` package

Service mesh integration in coordinated-worker charms requires:

- **Mandatory worker telemetry routing** through the coordinator for simplified policy management

This architecture enables coordinated-worker charms to benefit from service mesh security without requiring extensive mesh-specific code in each charm implementation.

## Further reading

- [Add service mesh support to coordinated-worker charms](../how-to/add-service-mesh-support-to-coordinated-worker-charms.md) - Implementation guide
- [Manage custom policies with PolicyResourceManager](../how-to/manage-custom-policies-with-policyresourcemanager.md) - Details on direct policy management
- [Traffic authorization](./traffic-authorization.md) - General authorization concepts in service meshes
- [Managed mode](./managed-mode.md) - How beacon charms manage policies automatically
