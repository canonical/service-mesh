# Cross-model mesh

When two applications integrated on a charmed service mesh live in different Juju models, the Beacon charm cannot generate a correct authorization policy from a normal Juju cross-model relation alone. The `cross_model_mesh` interface (exposed as the `provide-cmr-mesh` and `require-cmr-mesh` endpoints) exists to fill that gap, and it introduces one constraint on how cross-model offers must be structured.

## Why a dedicated cross-model interface is needed

A service mesh authorization policy identifies the source of allowed traffic by the workload's real identity. For Istio, the principal is `cluster.local/ns/<remote-model>/sa/<remote-app>`. To build this principal, the Beacon charm in the providing model needs to know two things about the consuming application:

* the **real application name** in the remote model
* the **real model name** the remote application is deployed in

Juju does not expose either of these across a cross-model relation. On the consumer side, an offer is consumed as a Software-as-a-Service (SAAS) under a local alias, and that local alias is the only name the providing side ever sees on the relation (`relation.app.name`). It has no relationship to the actual remote application name, and the remote model name is not surfaced at all.

The `cross_model_mesh` interface works around this by carrying the real `app_name` and `juju_model_name` of the consuming application explicitly in its relation data. The Beacon charm reads this payload and uses it, instead of the local SAAS alias, to build the source principal of the generated `AuthorizationPolicy`.

## How the correlation works

When Beacon builds policies, it iterates over each workload relation (for example `metrics-endpoint`, `reviews`, `ingress`) and, for each one, looks up the matching `cross_model_mesh` payload to discover the real source identity. The lookup key is the remote application as seen locally, that is, the local SAAS name on the relation.

This means the workload relation and the `cross_model_mesh` relation must arrive on the providing side under the **same** SAAS. Only then does the Beacon charm know that a given `cross_model_mesh` payload describes the source of a given workload relation.

## Limitation: group cross-model endpoints into a single offer

A Juju offer produces exactly one SAAS on the consumer side, and each SAAS in a consuming model must have a unique local name. As a direct consequence:

> All endpoints of a remote application that require an authorization policy, together with the `provide-cmr-mesh` endpoint, must be exposed through a **single** Juju offer.

If the workload endpoint and `provide-cmr-mesh` are exposed through separate offers, the consumer ends up with two different SAAS names backing the same remote application. The providing Beacon receives the two relations under two unrelated local names and cannot correlate them. The lookup silently falls back to the local SAAS alias as the source name, producing an `AuthorizationPolicy` whose source principal does not match any real workload. The policy is silently ineffective: cross-model traffic that should be allowed is denied (in hardened mode), or, if a permissive rule happens to match for unrelated reasons, granted under the wrong identity.

The same applies when multiple workload endpoints on a remote application each need their own policy. They must all be grouped into the single offer that also exposes `provide-cmr-mesh`. For example:

```bash
juju offer my-app:reviews,metrics-endpoint,ingress,provide-cmr-mesh
```

This is a structural limitation of Juju cross-model relations and cannot be worked around in the mesh charms or library. Future Juju support for surfacing the real remote application identity to the consumed side would remove the need for the `cross_model_mesh` interface and this grouping requirement.

## See also

* [Use the Istio mesh across different Juju models](../tutorial/use-the-istio-mesh-across-different-juju-models.md): tutorial walkthrough of a cross-model mesh setup.
* [Traffic authorization](./traffic-authorization.md): how authorization policies are generated in a charmed service mesh.
