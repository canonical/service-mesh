# Add Mesh Support to your Charm

This guide explains how to add service mesh support to your charm using the [ServiceMeshConsumer](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) library.  This library enables your charm to join a service mesh and automatically generate traffic authorization policies.

## Add Required Relations to `charmcraft.yaml`

To use the `ServiceMeshConsumer` library, add the following relations to your charm's `charmcraft.yaml`:

```yaml
requires:
  service-mesh:
    limit: 1
    interface: service_mesh
    description: |
      Integrate this charm into a service mesh
  require-cmr-mesh:
    interface: cross_model_mesh
    description: |
      If this app relates to other applications on a charmed service mesh cross-model, use this relation to send that related app additional data needed to automatically generate traffic authorization policies.  This is required because Juju does not natively provide all information required to build these policies when related cross-model.
provides:
  provide-cmr-mesh:
    interface: cross_model_mesh
    description: |
      If this app is generating polciies to provide access to related applications that are cross-model, relate that app to this additional relation to retrieve additional data required for these policies.  This is required because Juju does not natively provide all information required to build these policies when related cross-model.
```

## Use the `ServiceMeshConsumer` library in your charm

Fetch the [`service-mesh` library](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) and add the `ServiceMeshConsumer` to your Charm.  For example:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
    self._mesh = ServiceMeshConsumer(self)
```

This integration allows for your Charm to be integrated with a Charmed Beacon and [individually added to a Juju service mesh](./add-juju-applications-and-models-to-the-service-mesh.md).  By default, Charmed Service Meshes deploy [hardening](../explanation/hardened-mode.md), meaning they block any unauthorized access to your workloads.  If your Charm is never accessed by other applications in the cluster (ex: a Wordpress server that simply provides a website), you're done!  But if other applications need to access your charm, such as if you've charmed a database that other applications will relate to or a workload that has scrapable metrics, then continue below to create access policies.  

## Enable Automatic, Fine-grained Access to other Charmed Applications via Policies

In a [hardened](../explanation/hardened-mode.md) service mesh, communication between applications must be explicitly allowed by policies.  If your Charm deploys workloads that other applications consume, for example:

* your charm deploys a database and other applications consume this database by relating to your application
* your charm deploys any workload which generates metrics, and uses the [`prometheus_scrape`](https://charmhub.io/integrations/prometheus_scrape) interface to allow for metrics scraping

you can use the `ServiceMeshConsumer` `policies` argument to automate this policy generation[^1].  Each `Policy` defines:

* `relation`: the relation endpoint this policy applies to.  A policy will be generated for each application related via this relation
* `endpoints`: a list of `Endpoint` objects, each defining the `paths`, `ports`, and `methods` that this policy allows traffic on

For example:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
    self._mesh = ServiceMeshConsumer(
        self,
        policies=[
            Policy(
                relation="metrics-endpoint",  # On the metrics-endpoint relation
                endpoints=[                   # allow a related application to access...
                    Endpoint(
                        paths=["/metrics"],        # these specific paths
                        ports=[HTTP_LISTEN_PORT],  # on these specific ports
                        methods=[Method.get],      # using only these methods
                    ),
                ],
            ),
            Policy(
                relation="database",          # On the database relation
                endpoints=[                   # allow a related application to access...
                    Endpoint(
                        paths=["/db"],                     # these specific paths
                        ports=[DB_PORT],                   # on these specific ports
                        methods=[Method.get, Method.Post], # using only these methods
                    ),
                ],
            ),
        ],
    )
```

Exactly what should be defined for your `Endpoint`s depends on the application you've charmed.  Generally, you can look at your applications API reference or typical usage and include exactly what is needed, exposing only the necessary attack surface.  

## Cross-model Integrations (Optional)

If your Charm provides integrations that can be used cross-model, the `ServiceMeshConsumer` library offers the additional `provide-cmr-mesh` and `require-cmr-mesh` integrations to ensure these generate policies properly.  These additional integrations are required because Juju cross-model relations do not natively provide all the information needed for a service mesh authorization policy to be generated.  

To use the cross-model policy generation, simply integrate your applications normally and then add the additional cmr relation.  For example:

```
juju deploy my-db-provider
juju deploy my-db-consumer

juju relate my-db-provider:database my-db-consumer:database
juju relate my-db-provider:provide-cmr-support my-db-consumer:require-cmr-support
```

For a more detailed tutorial using cross-model integrations, follow the [Use the Istio Mesh across different Juju models](../tutorial/use-the-istio-mesh-across-different-juju-models.md) tutorial.

[^1]: For a detailed explanation of exactly what is generated automatically, see [Authorization Policy Creation in Istio](../explanation/traffic-authorization.md)
