# `tailscale_credentials` — Interface Specification

Provider: `tailscale-config`. Requirer: `tailscale-k8s` / `tailscale-beacon`.

## Purpose

Provider mints a scoped, per-relation credential against the control-plane API
and distributes it to one downstream charm; revokes it on relation removal.
One relation = one minted credential (multi-tenant across models/clusters).

## Transport

- Credential is sensitive → travels as a **Juju charm secret**, never as
  plaintext in the databag.
  - Provider: `secret-add` → `secret-grant` (scoped to the relation) → put the
    secret **URI** in the databag. See: https://canonical.com/juju/docs/ops/latest/howto/manage-secrets/#add-and-grant-access-to-a-secret
  - Requirer: read URI from databag → `secret-get`.
- Non-secret fields (`login-server`, `tags`) go in the provider app databag as
  plaintext.
- A Juju secret's content is a flat `dict[str, str]`: no nesting, string values
  only, dash-separated keys, 1MB per key.
- **Backend-agnostic hot path, backend-specific content.** The requirer's hot
  path is uniform: read `auth-key` from the secret, pass it to the operator /
  `tailscale up --auth-key`; the backend is distinguished by `login-server`.
  The secret *content* is nonetheless backend-specific — beyond `auth-key` it
  carries the credential's identifier(s), which differ per backend (see
  Relation data). The requirer only touches those extras for its own
  operator-tag self-check, not for joining the tailnet.

## Cross-controller / cross-model

- Works over a **cross-model relation (CMR)**, including across controllers and
  clouds. Only the secret URI crosses the databag; content is fetched on demand
  via Juju's controller channel (no secret-backend replication).
- Asymmetry to keep straight:
  - **Root credential** = user secret via `tailscale-config` config
    (`root-credential`). User secrets do NOT cross models/controllers → must be
    configured locally on `tailscale-config`. (Already the design.)
  - **Minted child credential** = charm secret over the relation → DOES cross
    the CMR to the downstream. This is the distribution path.
- Deployment prerequisite (operator-facing, not charmable): cross-controller
  CMR needs the controllers reachable — bootstrap with
  `--controller-external-ips` / `--controller-external-name` when the topology
  is not flat. Set at bootstrap only.

## Relation data

Provider app databag (published to the requirer):

| key            | type      | notes                                   |
|----------------|-----------|-----------------------------------------|
| `secret-id`    | str (URI) | URI of the granted credential secret    |
| `login-server` | str       | control-plane URL; empty for Tailscale SaaS |
| `tags`         | str       | comma-separated tag list (encoded)      |

- `tags` is **provider → requirer, informational.** The child inherits the
  parent (root) client's tags (spec: child carries the SAME tags as the
  parent); the requirer never supplies tags. It uses `tags` only to surface /
  cross-check what the credential carries for its local operator-tag self-check.

Credential secret content (`dict[str, str]`) — **backend-specific:**

*Tailscale backend:*

| key         | type | notes                                                        |
|-------------|------|--------------------------------------------------------------|
| `auth-key`  | str  | child OAuth client secret (`tskey-client-…`); passed to the operator / `tailscale up --auth-key` |
| `client-id` | str  | child OAuth client id (== the minted `key_id`); the requirer's operator-tag self-check reads `GET .../keys/{client-id}` |

*Headscale backend:*

| key        | type | notes                                              |
|------------|------|----------------------------------------------------|
| `auth-key` | str  | pre-auth key; passed to `tailscale up --auth-key`  |
| `id`       | str  | pre-auth key id (for the requirer's self-check / provider bookkeeping) |
| `prefix`   | str  | pre-auth key prefix                                |

- **Uniform hot path:** every backend exposes `auth-key`; the requirer joins
  the tailnet with that field alone and never branches on backend. The extra
  identifier field(s) are auxiliary — consumed only by the requirer's
  operator-tag self-check — and are co-located in the secret rather than the
  databag so all per-credential fields travel together in one `secret-get`.

## Provider lifecycle (reconciler)

- `relation-joined`/`changed`: mint child (idempotent) → record
  `relation-id → key_id` in the peer map → add + grant secret → publish
  `secret-id` + `login-server` + `tags`.
- `relation-broken`: look up `key_id` in the peer map → revoke child →
  drop the entry.
- Tailscale scopes for the mint are a **fixed provider-owned default**, not relation
  data; the requirer supplies none.
- Mint must be idempotent across hooks (don't re-mint if the peer map already
  holds a valid `key_id` for the relation).

### Peer relation (provider-internal)

The provider keeps a peer relation whose app databag holds the
`relation-id → key_id` map. This is the source of truth for idempotent mint
and for revoke-on-`relation-broken` (where the departing relation's own
databag is unreliable). Not part of the `tailscale_credentials` contract; the
requirer never sees it.
