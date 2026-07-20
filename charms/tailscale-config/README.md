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

```bash
# Provide the root credential (a Tailscale root OAuth client, or a Headscale
# API key) as a Juju user secret and grant it to the charm.
juju add-secret tailscale-root <key>=<value>
juju grant-secret tailscale-root tailscale-config

juju deploy tailscale-config
juju config tailscale-config \
  backend=tailscale \
  root-credential=secret:...   # the secret URI from `juju add-secret`
# For Headscale, also set: login-server=<headscale-url>

# Relate to downstream charms to distribute credentials automatically.
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
