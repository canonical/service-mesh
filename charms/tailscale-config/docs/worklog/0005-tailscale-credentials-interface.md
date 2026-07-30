# Worklog: `tailscale_credentials` interface

New thin Juju interface library for the `tailscale-credentials` relation
(provider `tailscale-config`, requirer `tailscale-k8s`/`tailscale-beacon`).

## Decisions

- **Thin boundary.** Library is pydantic models + databag/secret helpers only;
  no live `ops` calls. Charm owns secret `add_secret`/`grant`/`get_secret`, peer
  map, `login-server` substitution, and control-plane mint/revoke.
- **Sensitive credential via Juju secret.**
- Focus on Tailscale, Headscale future work.
- **Models own their serialization/validity**, not the wrapper classes:
  - `ProviderAppData.to_databag()` and `.is_ready_for_use()`.
  - `TailscaleCredentials.to_secret_content()`.
  - `is_ready` delegates to `is_ready_for_use()`
- **`tags`** are provider→requirer informational, comma-encoded on the wire;
  `None` = not populated, `[]` = present but empty.
- **`login_server` rejected when empty**, enforced on the model.
