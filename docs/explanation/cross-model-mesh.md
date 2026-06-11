# Cross-model mesh

The Beacon charm automatically generates authorization policies based on the Juju integrations that are in place at a given time. But, when two applications integrated with one another live in different Juju models, the Beacon charm cannot generate a correct authorization policy from a normal Juju cross-model relation and the `service-mesh` relation alone. The `cross_model_mesh` interface (exposed as the `provide-cmr-mesh` and `require-cmr-mesh` endpoints) exists to fill that gap, and it introduces one constraint on how cross-model offers must be structured.

## Why a dedicated cross-model interface is needed

A service mesh authorization policy identifies the source of allowed traffic by the workload's real identity. For Istio, the principal is `cluster.local/ns/<remote-model>/sa/<remote-app>`. To build this principal, the Beacon charm in the providing model needs to know two things about the consuming application:

* the **real application name** in the remote model
* the **real model name** the remote application is deployed in

Juju does not expose either of these across a cross-model relation. On the consumer side, an offer is consumed as a Software-as-a-Service (SaaS) under a local alias, and that local alias is the only name the providing side ever sees on the relation (`relation.app.name`). It has no relationship to the actual remote application name, and the remote model name is not surfaced at all.

The `cross_model_mesh` interface works around this by carrying the real `app_name` and `juju_model_name` of the consuming application explicitly in its relation data. The Beacon charm reads this payload and uses it, instead of the local SaaS alias, to build the source principal of the generated `AuthorizationPolicy`.

## How the correlation works

When Beacon builds policies, it iterates over each relation that a policy applies to (for example an established relation on the `metrics-endpoint`, `reviews`, or `ingress` charm endpoint) and looks up the matching `cross_model_mesh` relation to discover the real source identity. The lookup key is the remote application as seen locally, that is, the local SaaS name on the relation.

This means both relations must arrive on the providing side under the **same** SaaS. Only then does the Beacon charm know that a given `cross_model_mesh` payload describes the source of a given relation.

## Limitation: every offer with a workload endpoint must also include `provide-cmr-mesh`

A Juju offer produces exactly one SaaS on the consumer side, and each SaaS in a consuming model has its own unique local name. Because Beacon correlates a charm relation with its corresponding `cross_model_mesh` relation data by **matching the local SaaS name on both relations**, the rule is:

> Every Juju offer that exposes an endpoint requiring an authorization policy must also expose the `provide-cmr-mesh` endpoint.

If a charm endpoint is exposed in an offer that does not also include `provide-cmr-mesh`, the consumer ends up with a SaaS for the charm relation that has no matching `cross_model_mesh` endpoint under the same local name. The providing Beacon silently falls back to the local SaaS alias as the source name, and produces an `AuthorizationPolicy` whose source principal does not match any real charm's principal. The policy is silently ineffective: cross-model traffic that should be allowed is denied (in hardened mode), or, if a permissive rule happens to match for unrelated reasons, granted under the wrong identity.

There are two equivalent ways to satisfy the rule:

* **One offer bundling everything.** Group all charm endpoints together with `provide-cmr-mesh` into a single offer:

  ```bash
  juju offer my-app:reviews,metrics-endpoint,ingress,provide-cmr-mesh
  ```

* **Multiple offers, each one self-contained.** Re-expose `provide-cmr-mesh` in every offer that carries a charm endpoint:

  ```bash
  juju offer my-app:reviews,provide-cmr-mesh           # consumed as e.g. my-app-reviews
  juju offer my-app:metrics-endpoint,provide-cmr-mesh  # consumed as e.g. my-app-metrics
  ```

  Each offer becomes its own SaaS on the consumer side, and each SaaS carries both a workload relation and a `cross_model_mesh` relation under the same local name, so Beacon correlates each pair independently.

## See also

* [Use the Istio mesh across different Juju models](../tutorial/use-the-istio-mesh-across-different-juju-models.md): tutorial walkthrough of a cross-model mesh setup.
* [Traffic authorization](./traffic-authorization.md): how authorization policies are generated in a charmed service mesh.
