# Leon Review Bot — charm best practices

Recurring review feedback distilled from PR #114 (envoy-ai-controller-k8s), kept only
where it generalizes to any charm in this repo. Run this as a checklist against a charm
before opening it for review. Each item is the rule, why it exists, and how to check it.

## charmcraft.yaml / packaging

1. **No dead, 404, or self-referential links.** Every `links:` URL must resolve; do not
   set `website` to the charm's own Charmhub listing (violates the listing guideline).
   Drop links entirely until a real page exists rather than pointing at a placeholder.
   *Check:* curl each URL; confirm `website` isn't the charm's own page.

2. **Track the latest Ubuntu base.** Use the newest supported base (e.g.
   `ubuntu@26.04:amd64`) unless there's a concrete blocker.
   *Check:* the `base`/`platforms` entry isn't pinned to an older LTS without reason.

3. **Name relations and interfaces after upstream nomenclature.** When wrapping an
   upstream component, mirror its naming (e.g. `envoy_extension_server`) rather than
   inventing a charm-local term. Shorter isn't better if it loses the upstream mapping.
   *Check:* relation/interface names trace back to an upstream concept.

4. **Comment rare or surprising declarations.** Anything a reader wouldn't expect —
   `optional: false` on a relation, an unusual resource type — gets a one-line comment
   stating why.
   *Check:* every non-default metadata choice is either obvious or commented.

5. **Remove unused scaffolded dependencies.** Template-generated deps that the charm
   doesn't use (e.g. a stray `asyncio`) must be dropped.
   *Check:* every dependency in pyproject.toml is actually imported.

## Config

6. **Invalid non-critical config warns and falls back — in code, not just docs.** Don't
   only document the fallback in the option description; enforce it in the charm so an
   invalid value logs a warning and uses the default instead of reaching the workload
   and failing to start. The guardrail is self-documenting.
   *Check:* each enum/bounded config option has a validate-and-fallback path.

## Charm class / logic

7. **Probe the workload for truth; don't hardcode a const.** Prefer reading state from
   the running workload (on pebble-ready) over a baked-in literal — less maintenance and
   CI logic to keep the const honest.
   *Check:* version/health/capability values come from the workload where feasible.

8. **Extract reusable infrastructure logic into the shared package.** Mechanisms that
   repeat across charms (CRD apply + wait-for-Established, resource management) belong in
   `canonical_service_mesh`, not copied into each charm. Keep the CharmBase class slim.
   *Check:* CRD handling uses `CustomResourceDefinitionManager`; no per-charm copy of the
   apply/established mechanism.

9. **Helpers fail safe.** A predicate that can't determine state returns the negative
   (e.g. "not healthy") rather than a false positive. Never `return True` on an error path.
   *Check:* every `except` in a bool helper returns False / the safe default.

10. **Comment load-bearing or intentionally-omitted logic.** Non-obvious control flow
    (early `return`s that encode status priority) and deliberate omissions (why CRDs are
    *not* deleted on remove) get a comment explaining the reason — not a vague or outdated
    reference.
    *Check:* surprising code and "why isn't X here" gaps are explained.

11. **Status messages: short, consistent, workload-named.** Use the container/workload
    name (e.g. `Waiting for ai-gateway container`, `Waiting for ai-gateway to become
    healthy`), not styled prose ("AI Gateway"). Consistency helps admins drill down in
    `juju status`.
    *Check:* all `add_status` messages use the same naming and are terse.

## TLS / certificates

12. **No CN in certificate requests; put every name in SANs.** The spec requires the CN
    to match a SAN, and a service FQDN can exceed the 64-char X.509 CN limit. Omit the CN
    and list every dial-able name in `sans_dns`.
    *Check:* `CertificateRequestAttributes` sets SANs only, no `common_name`.

## Observability

13. **No hand-written `up == 0` / `absent(up)` alerts.** cos-lib auto-generates target-down
    and absence alerts; remove them from the charm's rules files.
    *Check:* alert rules contain no `up == 0` or `absent(up(...))` expressions.

## Documentation

14. **Charm ships a README following the repo's shared structure.** Every charm has a
    top-level `README.md` that mirrors the sibling charms' sections and order (intro of
    what the charm owns/does, a Relations table, a How It Works walkthrough with a mermaid
    diagram, a Lifecycle sequence diagram, a CRDs/provenance section, and a Configuration
    pointer). Match the existing charm's wording and layout rather than inventing a new one.
    *Check:* the README exists and its sections line up with a sibling charm's README.

15. **Vendored upstream files carry provenance.** Any manifest copied from upstream
    (CRDs, RBAC) documents its source repo and version so future bumps are traceable —
    prefer a section in the charm README (e.g. a CRDs table listing directory → source →
    version) over scattering it, and tie the version to the resource tag in charmcraft.yaml
    where one exists.
    *Check:* the README (or a directory README/header) states each vendored dir's source and version.

## Tests

16. **Derive test constants from the source of truth.** Don't duplicate a literal (image
    ref, default tag) in tests; read it from charmcraft.yaml/metadata so the two can't
    drift.
    *Check:* test fixtures parse values from the packaging files rather than re-declaring
    them.
