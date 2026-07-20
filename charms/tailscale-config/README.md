# tailscale-config

tailscale-config is a workloadless charm that acts as the central credential
authority for a charmed Tailscale/Headscale solution. It mints a scoped
credential per downstream relation (a child OAuth client for Tailscale, a
pre-auth key for Headscale) and distributes it to `tailscale-k8s` and
`tailscale-beacon`, revoking it again when the relation is removed.

A single tailscale-config is multi-tenant — it can serve many downstream charms
across many models and clusters at once — and holds no cluster/tailnet state
beyond the root credential it needs to reach the control-plane API, so it can
run on or off the cluster.

## Usage

### Tailscale backend

Create a root OAuth client in the Tailscale admin console (with the
`oauth_keys` scope plus the union of scopes it will delegate) and store its
`client-id` and `client-secret` in a Juju user secret:

```bash
# Store the root OAuth client credentials and grant the secret to the charm.
juju add-secret tailscale-root \
  client-id=<oauth-client-id> \
  client-secret=tskey-client-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
juju grant-secret tailscale-root tailscale-config

juju deploy tailscale-config
juju config tailscale-config \
  backend=tailscale \
  root-credential=secret:...   # the secret URI printed by `juju add-secret`

# Verify the root client is reachable and inspect its scopes.
juju run tailscale-config/leader get-root-client-info

# Relate to downstream charms to distribute credentials automatically.
juju integrate tailscale-config tailscale-k8s
juju integrate tailscale-config tailscale-beacon
```

### Headscale backend

```bash
# Store the Headscale API key and grant the secret to the charm.
juju add-secret tailscale-root api-key=<headscale-api-key>
juju grant-secret tailscale-root tailscale-config

juju deploy tailscale-config
juju config tailscale-config \
  backend=headscale \
  login-server=<headscale-url> \
  root-credential=secret:...   # the secret URI printed by `juju add-secret`

juju integrate tailscale-config tailscale-k8s
juju integrate tailscale-config tailscale-beacon
```

tailscale-config is optional: `tailscale-k8s` and `tailscale-beacon` are fully
functional standalone via manual credential config. tailscale-config exists to
automate credential minting and revocation, and is the recommended
default at scale.

## Other resources

- [Contributing](CONTRIBUTING.md)

- See the [Juju documentation](https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/) for more information about developing and improving charms.
