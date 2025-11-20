# Add Service Mesh Support to Coordinated-Worker Charms

This guide explains how to add service mesh support to charms that use the [`coordinated-workers`](https://github.com/canonical/cos-coordinated-workers) Python package. The package provides built-in service mesh integration that handles cluster-internal policies and worker telemetry routing automatically.

```{note}
Service mesh support in the `coordinated-workers` package is available from version **v2.1.0** and later.
```

## Prerequisites

This guide assumes you have:
- A charm already using the [`coordinated-workers`](https://github.com/canonical/cos-coordinated-workers) package (v2.1.0 or later) with a coordinator and worker charm
- Basic knowledge of [service mesh concepts](../explanation/service-mesh.md)
- Familiarity with [adding mesh support to charms](./add-mesh-support-to-your-charm.md)
- Understanding of [traffic authorization](../explanation/traffic-authorization.md) in charmed service meshes

```{note}
This guide is specifically for charms using the `coordinated-workers` package (like Tempo, Loki, and Mimir). If you're adding mesh support to a standard charm, see [Add Mesh Support to your Charm](./add-mesh-support-to-your-charm.md) instead.
```

## Overview

The `coordinated-workers` package provides automatic service mesh integration for coordinator-worker architectures. When enabled, it:

- Automatically manages [cluster-internal authorization policies](../explanation/service-mesh-in-coordinated-worker-charms.md#cluster-internal-policies) between the coordinator and workers
- Routes all worker telemetry (metrics, logs, traces) through the coordinator for simplified policy management
- Allows charm authors to define additional charm-specific policies for external relations

## Add the service mesh library to both coordinator and worker charms

```{important}
Both the **coordinator** and **worker** charms must fetch the `service_mesh` library, even though the worker charm won't use it directly in code. The `coordinated-workers` package requires this library to be present in both charms to function correctly.
```

### Fetch the library

In both your coordinator and worker charm directories, fetch the `service_mesh` library:

```bash
# In your coordinator charm directory
charmcraft fetch-lib charms.istio_beacon_k8s.v0.service_mesh

# In your worker charm directory
charmcraft fetch-lib charms.istio_beacon_k8s.v0.service_mesh
```

### Add required dependencies

The `service_mesh` library has dependencies that must be added to the `requirements.txt` file in **both coordinator and worker charms**:

```text
# In requirements.txt for BOTH coordinator and worker
charmed-service-mesh-helpers>=0.2.0
lightkube-extensions
```

```{note}
Even though the worker charm doesn't directly use the `service_mesh` library in its code, these dependencies are required because the `coordinated-workers` package imports and uses the library internally when managing cluster-internal policies.
```

## Add service mesh relations to your coordinator charm

### Step 1: Add required relations to `charmcraft.yaml`

Add the following relations to your **coordinator** charm's `charmcraft.yaml`:

```yaml
requires:
  service-mesh:
    limit: 1
    interface: service_mesh
    description: |
      Subscribe this charm into a service mesh and create the necessary authorization policies.
  require-cmr-mesh:
    interface: cross_model_mesh
    description: |
      Allow a cross-model application access to this charm via the service mesh.
      This relation provides additional data required by the service mesh to enforce cross-model authorization policies.

provides:
  provide-cmr-mesh:
    interface: cross_model_mesh
    description: |
      Allow cross-model applications to make HTTP requests to this charm via the service mesh.
      This relation provides additional data required by the service mesh to create cross-model authorization policies.
```

```{note}
The worker charm does not require any service mesh relations in its `charmcraft.yaml`. All mesh configuration is handled by the coordinator. However, the worker charm **must** still have the `service_mesh` library and its dependencies installed.
```

### Step 2: Configure service mesh endpoints in Coordinator initialization

Update your `Coordinator` instantiation to include the service mesh endpoint names:

```python
from coordinated_workers.coordinator import Coordinator

class MyCoordinatorCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.coordinator = Coordinator(
            charm=self,
            roles_config=MY_ROLES_CONFIG,
            external_url=self._external_url,
            worker_metrics_port=WORKER_METRICS_PORT,
            endpoints={
                "certificates": "certificates",
                "cluster": "tempo-cluster",  # Your cluster relation name
                "grafana-dashboards": "grafana-dashboard",
                "logging": "logging",
                "metrics": "metrics-endpoint",
                "s3": "s3",
                "charm-tracing": "self-charm-tracing",
                "workload-tracing": "self-workload-tracing",
                "send-datasource": None,
                "receive-datasource": "receive-datasource",
                "catalogue": "catalogue",
                # Service mesh endpoints
                "service-mesh": "service-mesh",
                "service-mesh-provide-cmr-mesh": "provide-cmr-mesh",
                "service-mesh-require-cmr-mesh": "require-cmr-mesh",
            },
            nginx_config=my_nginx_config,
            workers_config=self._get_workers_config,
            # ... other parameters
        )
```

The `Coordinator` class will automatically:
- Initialize a `ServiceMeshConsumer` with the specified endpoints
- Create cluster-internal policies for coordinator-worker communication
- Handle mesh label reconciliation on coordinator and worker pods

### Step 3: Define charm-specific mesh policies

Create a method that returns policies specific to your charm's external relations. These policies control access from applications that relate to your coordinator (not the internal cluster communication):

```python
from charms.istio_beacon_k8s.v0.service_mesh import (
    AppPolicy,
    UnitPolicy,
    Endpoint,
    Method,
)

class MyCoordinatorCharm(CharmBase):
    @property
    def _charm_mesh_policies(self) -> List[Union[AppPolicy, UnitPolicy]]:
        """Return mesh policies specific to this charm.

        These policies cover access from charms relating to this coordinator over
        charm-specific relations. Cluster-internal policies (coordinator <-> workers)
        are managed automatically by the Coordinator class.
        """
        return [
            # Allow access from applications related via the "api" relation
            AppPolicy(
                relation="api",
                endpoints=[
                    Endpoint(
                        ports=[HTTP_PORT, GRPC_PORT],
                        # No methods/paths restriction - allow all
                    )
                ],
            ),
            # Allow Grafana to query this charm's API
            AppPolicy(
                relation="grafana-source",
                endpoints=[
                    Endpoint(
                        ports=[HTTP_PORT],
                    )
                ],
            ),
            # Allow Prometheus to scrape metrics from coordinator units
            UnitPolicy(
                relation="metrics-endpoint",
                ports=[METRICS_PORT],
            ),
        ]
```

```{note}
You only need to define policies for relations that are **external** to your coordinated-worker cluster. The `Coordinator` automatically manages policies for:
- Coordinator to worker communication
- Worker to coordinator communication
- Worker to worker communication
- Metrics scraping from worker units (when worker telemetry proxying is enabled)
```

### Step 4: Enable worker telemetry proxying

Configure the coordinator to proxy worker telemetry by defining a `WorkerTelemetryProxyConfig`:

```python
from coordinated_workers.worker_telemetry import WorkerTelemetryProxyConfig

class MyCoordinatorCharm(CharmBase):
    @property
    def _worker_telemetry_proxy_config(self) -> WorkerTelemetryProxyConfig:
        """Configure the port for proxying worker telemetry through the coordinator."""
        return WorkerTelemetryProxyConfig(
            http_port=TELEMETRY_PROXY_PORT,
            https_port=TELEMETRY_PROXY_PORT,
        )
```

Then pass both the policies and telemetry config to the `Coordinator`:

```python
self.coordinator = Coordinator(
    charm=self,
    # ... other parameters
    worker_telemetry_proxy_config=self._worker_telemetry_proxy_config,
    charm_mesh_policies=self._charm_mesh_policies,
)
```

```{important}
Worker telemetry proxying is **mandatory** when using service mesh with coordinated-workers. This routing ensures that all worker telemetry (metrics, logs, traces, remote-write) flows through the coordinator, which:
- Simplifies authorization policy management (fewer policies needed)
- Provides a single point of egress from the cluster
- Enables the coordinator to enforce consistent access control

See the [service mesh architecture explanation](../explanation/service-mesh-in-coordinated-worker-charms.md#worker-telemetry-routing) for details on why this is required.
```

### Step 5: Open the telemetry proxy port

Ensure your coordinator charm opens the port specified in your `WorkerTelemetryProxyConfig`:

```python
def _reconcile(self):
    # ... your existing reconciliation logic

    # Open the worker telemetry proxy port
    self.unit.set_ports(
        *self._nginx_ports,
        TELEMETRY_PROXY_PORT  # The port from WorkerTelemetryProxyConfig
    )
```

## Further reading

- Learn about the [service mesh architecture in coordinated-worker charms](../explanation/service-mesh-in-coordinated-worker-charms.md)
- Understand [how to manage custom policies with PolicyResourceManager](./manage-custom-policies-with-policyresourcemanager.md) for advanced use cases
- Explore [traffic authorization concepts](../explanation/traffic-authorization.md) in service meshes
- See [managed mode](../explanation/managed-mode.md) for details on automatic policy generation
- View the [`coordinated-workers` package repository](https://github.com/canonical/cos-coordinated-workers) for more information
