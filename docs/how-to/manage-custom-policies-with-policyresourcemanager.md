# Manage Custom Service Mesh Policies with PolicyResourceManager

This guide explains how to use the `PolicyResourceManager` class to create and manage custom service mesh authorization policies directly from your charm. This is an advanced feature for scenarios where the automatic policy generation provided by `ServiceMeshConsumer` is not sufficient.

## Prerequisites

This guide assumes you have:
- Basic knowledge of Juju charms and charm development
- Understanding of [service mesh concepts](../explanation/service-mesh.md)
- Familiarity with [adding mesh support to charms](./add-mesh-support-to-your-charm.md)
- Understanding of [how traffic authorization works](../explanation/traffic-authorization.md) in charmed service meshes

## Understanding automatic vs. custom policy management

Before using `PolicyResourceManager`, it's important to understand how policy management works in Charmed Service Mesh:

### Automatic policy management with ServiceMeshConsumer

When you [add mesh support to your charm](./add-mesh-support-to-your-charm.md) using `ServiceMeshConsumer`, your charm integrates with a beacon charm (like `istio-beacon-k8s`) via the `service-mesh` relation. In [managed mode](../explanation/managed-mode.md), the beacon charm automatically generates authorization policies based on your Juju relations and the `AppPolicy` or `UnitPolicy` definitions you provide.

The beacon charm manages these policies completely - creating, updating, and deleting them as relations change. This works well for typical charm-to-charm communication patterns.

### Custom policy management with PolicyResourceManager

`PolicyResourceManager` gives you direct control to create policies that don't follow the automatic relation-based pattern. Unlike `ServiceMeshConsumer`, where policies are managed by the beacon charm, `PolicyResourceManager` allows your charm to create and manage its own `AuthorizationPolicy` resources directly in Kubernetes.

## When to use PolicyResourceManager

Consider using `PolicyResourceManager` in situations like, but not limited to:

1. **Custom policy requirements**: Your authorization policies cannot be expressed through the relation-based approach of `ServiceMeshConsumer`
2. **Non-related applications**: You need to manage policies between applications that are not related via Juju relations
3. **Operating without managed mode**: You're working in an environment where the beacon's [managed mode](../explanation/managed-mode.md) is disabled

```{note}
For most charms, the `ServiceMeshConsumer` with `AppPolicy` and `UnitPolicy` is sufficient and recommended. Only use `PolicyResourceManager` if you have specific requirements that cannot be met by the automatic policy generation provided by the `service-mesh` relation.
```

## How PolicyResourceManager identifies and owns resources

The `PolicyResourceManager` uses Kubernetes labels to identify and manage the policy resources it creates. This label-based ownership model is critical to understand:

### Label-based resource identification

When you instantiate a `PolicyResourceManager` with specific labels:

```python
PolicyResourceManager(
    charm=self,
    lightkube_client=client,
    labels={
        "app.kubernetes.io/instance": f"{self.app.name}-{self.model.name}",
        "kubernetes-resource-handler-scope": "cluster-internal",
    },
)
```

These labels serve two purposes:

1. **Resource tagging**: Every policy resource created by this `PolicyResourceManager` instance will be tagged with these labels
2. **Resource querying**: When calling `reconcile()` or `delete()`, the `PolicyResourceManager` queries Kubernetes for all resources matching these labels to determine what it currently owns

### Why labels must be unique

The labels you provide **must be unique** to this specific `PolicyResourceManager` instance. This ensures:

- **Complete ownership**: The `PolicyResourceManager` can safely delete any resource with these labels without affecting resources managed by other components
- **Clean reconciliation**: During `reconcile()`, the manager can accurately determine which existing resources should be kept, updated, or deleted
- **No conflicts**: Multiple `PolicyResourceManager` instances (even in the same charm) can coexist as long as they use different label sets

```{warning}
If you use the same labels for multiple `PolicyResourceManager` instances, they will conflict and may delete each other's resources. Always ensure your label combination is unique to each policy manager instance.
```

### Practical labeling strategy

A good labeling strategy combines:

```python
labels = {
    # Identifies which charm/model created this resource
    "app.kubernetes.io/instance": f"{self.app.name}-{self.model.name}",

    # Identifies the purpose/scope within the charm
    "kubernetes-resource-handler-scope": "descriptive-scope-name",
}
```

For example, if a single charm needs to manage multiple sets of policies:

```python
# Manager for cluster-internal policies
internal_prm = PolicyResourceManager(
    charm=self,
    lightkube_client=client,
    labels={
        "app.kubernetes.io/instance": f"{self.app.name}-{self.model.name}",
        "kubernetes-resource-handler-scope": "cluster-internal",
    },
)

# Manager for external service policies
external_prm = PolicyResourceManager(
    charm=self,
    lightkube_client=client,
    labels={
        "app.kubernetes.io/instance": f"{self.app.name}-{self.model.name}",
        "kubernetes-resource-handler-scope": "external-services",
    },
)
```

Each manager can independently reconcile its own set of policies without interfering with the other.

## Add PolicyResourceManager to your charm

### Step 1: Import the required classes

First, fetch the [`service-mesh` library](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) and import the necessary classes in your charm:

```python
from charms.istio_beacon_k8s.v0.service_mesh import (
    Endpoint,
    MeshPolicy,
    Method,
    PolicyResourceManager,
    PolicyTargetType,
    ServiceMeshConsumer,
)
from lightkube import Client
```

### Step 2: Instantiate the PolicyResourceManager

Create a method in your charm to instantiate the `PolicyResourceManager`:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        # Your existing ServiceMeshConsumer (optional but recommended)
        self._mesh = ServiceMeshConsumer(self)

        # Observe events where policies need reconciliation
        self.framework.observe(self.on.config_changed, self._reconcile_policies)
        self.framework.observe(self.on.remove, self._on_remove)

    def _get_policy_manager(self) -> PolicyResourceManager:
        """Return a PolicyResourceManager instance."""
        return PolicyResourceManager(
            charm=self,
            lightkube_client=Client(
                field_manager=f"{self.app.name}-{self.model.name}"
            ),
            labels={
                "app.kubernetes.io/instance": f"{self.app.name}-{self.model.name}",
                "kubernetes-resource-handler-scope": f"{self.app.name}-custom-policies",
            },
            logger=self.logger,
        )
```

```{note}
The `lightkube_client` **must** be instantiated with a `field_manager` parameter. This is required for Kubernetes server-side apply operations. A good practice is to use your application name combined with the model name to ensure uniqueness.
```

### Step 3: Define your custom MeshPolicy objects

Create a method that returns the list of policies you want to manage:

```python
def _get_custom_policies(self) -> List[MeshPolicy]:
    """Return the list of custom mesh policies to reconcile."""
    policies = []

    # Example 1: Allow app-a to access app-b's service on specific endpoints
    policies.append(
        MeshPolicy(
            source_namespace="model-a",
            source_app_name="app-a",
            target_namespace="model-b",
            target_app_name="app-b",
            target_type=PolicyTargetType.app,
            endpoints=[
                Endpoint(
                    ports=[8080, 443],
                    methods=[Method.get, Method.post],
                    paths=["/api/*", "/health"],
                )
            ],
        )
    )

    # Example 2: Allow app-a to access all units with specific labels
    policies.append(
        MeshPolicy(
            source_namespace="model-a",
            source_app_name="app-a",
            target_namespace="model-b",
            target_selector_labels={
                "app.kubernetes.io/name": "worker-app",
                "cluster-role": "worker",
            },
            target_type=PolicyTargetType.unit,
            endpoints=[
                Endpoint(ports=[9090])
            ],
        )
    )

    return policies
```

### Step 4: Reconcile policies in your charm's event handlers

Call the `reconcile()` method to create or update the policies:

```python
def _reconcile_policies(self, event):
    """Reconcile custom mesh policies."""
    if not self.unit.is_leader():
        return

    # Get the mesh type from ServiceMeshConsumer (if using it)
    mesh_type = self._mesh.mesh_type()
    if not mesh_type:
        self.logger.info("No active service mesh connection, skipping policy reconciliation")
        return

    prm = self._get_policy_manager()
    policies = self._get_custom_policies()

    # Reconcile will create, update, or delete policies as needed
    prm.reconcile(policies, mesh_type)
```

### Step 5: Clean up on removal

Ensure policies are deleted when your charm is removed:

```python
def _on_remove(self, event):
    """Clean up custom policies on charm removal."""
    if not self.unit.is_leader():
        return

    prm = self._get_policy_manager()
    prm.delete()
```

## Understanding MeshPolicy configuration

A `MeshPolicy` defines a complete authorization policy with the following key fields. For more details on how these policies translate to actual authorization rules, see the [traffic authorization documentation](../explanation/traffic-authorization.md).

### Source configuration
- **`source_namespace`**: The Juju model (Kubernetes namespace) of the application making the request
- **`source_app_name`**: The name of the Juju application making the request

### Target configuration
- **`target_namespace`**: The Juju model (Kubernetes namespace) of the target application
- **`target_type`**: Either `PolicyTargetType.app` or `PolicyTargetType.unit`

### App-targeted policies vs. Unit-targeted policies

The behavior differs significantly based on the `target_type`. For a detailed explanation of these policy types, see the [charm mesh support guide](./add-mesh-support-to-your-charm.md#enable-automatic-fine-grained-access-to-other-charmed-applications-via-policies).

For **app-targeted policies** (`PolicyTargetType.app`):
- Traffic is directed to the target application's Kubernetes **Service** address
- Supports fine-grained Layer 7 (HTTP) access control
- **`target_app_name`**: The name of the target Juju application
- **`target_service`**: (Optional) The Kubernetes service name if different from the app name
- **`endpoints`**: List of `Endpoint` objects with `ports`, `methods`, `paths`, and `hosts`

For **unit-targeted policies** (`PolicyTargetType.unit`):
- Traffic is directed to individual **Pods** (units) of the target application
- Supports Layer 4 (TCP) access control only
- **`target_app_name`**: The name of the target Juju application, OR
- **`target_selector_labels`**: A dictionary of Kubernetes labels to select target pods
- **`endpoints`**: List of `Endpoint` objects with only `ports` (methods, paths, and hosts are not supported)

```{note}
Unit-targeted policies provide Layer 4 (TCP) access control to individual pods. They cannot restrict by HTTP methods, paths, or hosts - only by ports. This limitation comes from the underlying Istio service mesh implementation. Use unit policies when you need to access individual units directly, such as for metrics scraping from each pod.
```

## Using raw policy objects

For advanced use cases where `MeshPolicy` doesn't provide enough flexibility, you can pass pre-built policy objects directly to the `PolicyResourceManager` using the `raw_policies` parameter.

### When to use raw policies

Use `raw_policies` when you need:
- Mesh-specific features not exposed by the mesh-agnostic `MeshPolicy` abstraction
- Full control over the native policy specification
- Direct translation of existing mesh-specific policies to your charm

```{note}
`MeshPolicy` is designed to be mesh-agnostic. If your policy requirements are specific to a particular mesh implementation, `raw_policies` gives you direct access to the underlying policy format.
```

### Available policy types

Currently, the following raw policy types are supported:

**For Istio mesh:**
- `AuthorizationPolicy` - available from `lightkube_extensions.types`

### Building raw policies for Istio

Import the `AuthorizationPolicy` type and spec models:

```python
from lightkube.models.meta_v1 import ObjectMeta
from lightkube_extensions.types import AuthorizationPolicy
from charmed_service_mesh_helpers.models import (
    AuthorizationPolicySpec,
    From,
    Operation,
    PolicyTargetReference,
    Rule,
    Source,
    To,
)
```

```{note}
The `AuthorizationPolicy` resource type is provided by `lightkube_extensions`, while the spec data models (`AuthorizationPolicySpec`, `Rule`, etc.) are provided by `charmed_service_mesh_helpers`. There are ongoing plans to consolidate the service mesh library offerings into a single, unified Python package.
```

Create an `AuthorizationPolicy` using the data models:

```python
def _get_raw_policies(self) -> list[AuthorizationPolicy]:
    """Return raw AuthorizationPolicy objects."""
    policy = AuthorizationPolicy(
        metadata=ObjectMeta(
            name="my-custom-policy",
            namespace=self.model.name,
        ),
        spec=AuthorizationPolicySpec(
            targetRefs=[
                PolicyTargetReference(
                    kind="Service",
                    group="",
                    name="target-service",
                )
            ],
            rules=[
                Rule(
                    from_=[
                        From(
                            source=Source(
                                principals=[
                                    f"cluster.local/ns/{self.model.name}/sa/source-app"
                                ]
                            )
                        )
                    ],
                    to=[
                        To(
                            operation=Operation(
                                ports=["8080"],
                                methods=["GET", "POST"],
                                paths=["/api/*"],
                            )
                        )
                    ],
                )
            ],
        ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
    )
    return [policy]
```

```{note}
The `AuthorizationPolicySpec` is a Pydantic model. Use `.model_dump(by_alias=True, exclude_unset=True, exclude_none=True)` to convert it to the dict format expected by `AuthorizationPolicy.spec`.
```

### Reconciling raw policies

Pass `raw_policies` to `reconcile()` alongside or instead of `MeshPolicy` objects:

```python
def _reconcile_policies(self, event):
    prm = self._get_policy_manager()
    mesh_type = self._mesh.mesh_type()

    # Use both MeshPolicy and raw policies together
    prm.reconcile(
        self._get_custom_policies(),
        mesh_type,
        raw_policies=self._get_raw_policies(),
    )

    # Or use only raw policies
    prm.reconcile([], mesh_type, raw_policies=self._get_raw_policies())
```

The `PolicyResourceManager` will apply the configured labels to raw policies and manage them alongside any `MeshPolicy`-generated policies.

## Best practices

### Combining ServiceMeshConsumer and PolicyResourceManager

You can use both `ServiceMeshConsumer` and `PolicyResourceManager` together:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        # ServiceMeshConsumer for standard relation-based policies
        # These are managed automatically by the beacon charm
        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                AppPolicy(
                    relation="database",
                    endpoints=[
                        Endpoint(ports=[5432], methods=[Method.get, Method.post])
                    ]
                )
            ]
        )

    def _reconcile_custom_policies(self, event):
        """Manage custom policies that can't be expressed via relations."""
        # Get mesh type from ServiceMeshConsumer
        mesh_type = self._mesh.mesh_type()
        if mesh_type:
            prm = self._get_policy_manager()
            # These policies are managed directly by your charm
            prm.reconcile(self._get_custom_policies(), mesh_type)
```

This approach gives you:
- Automatic policy management for standard charm-to-charm communication via the `service-mesh` relation
- Custom policy management for special cases that don't fit the standard pattern

### Reconciliation timing

Call `reconcile()` in response to events that affect your policies:

- When cluster topology changes (e.g., relation added/removed)
- On config-changed if policies depend on configuration
- On upgrade-charm to ensure policies are up to date
- When mesh connection is established (e.g., `service-mesh` relation created)

### Handling empty policy lists

The `reconcile()` method handles empty policy lists gracefully by deleting all managed resources:

```python
# If no policies are needed, pass an empty list
prm.reconcile([], mesh_type)

# This is equivalent to:
prm.delete()
```

## Further reading

- Learn more about [service mesh concepts](../explanation/service-mesh.md)
- Understand [traffic authorization in charmed service meshes](../explanation/traffic-authorization.md)
- Learn about [managed mode](../explanation/managed-mode.md) and automatic policy generation
- Read the [how-to guide for adding mesh support](./add-mesh-support-to-your-charm.md) to understand `AppPolicy` and `UnitPolicy`
- Explore the [service_mesh library API documentation](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh)
- See how authorization policies work in [Istio documentation](https://istio.io/latest/docs/reference/config/security/authorization-policy/)
