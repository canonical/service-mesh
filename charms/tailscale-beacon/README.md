# tailscale-beacon

`tailscale-beacon` is a subordinate machine charm that installs the Tailscale
snap and joins the host to a tailnet. All workloads on the machine become
reachable subject to the tailnet ACL policy.

The charm supports Ubuntu 24.04 and Ubuntu 26.04.

## Usage with tailscale-config

```bash
juju deploy tailscale-beacon
juju integrate tailscale-beacon:juju-info <principal>:juju-info
juju integrate tailscale-config tailscale-beacon
```

## Manual credentials

```bash
juju add-secret tailscale-auth auth-key=<auth-key>
juju grant-secret tailscale-auth tailscale-beacon
juju config tailscale-beacon credentials=secret:<id>
juju integrate tailscale-beacon:juju-info <principal>:juju-info
```

For a Headscale-coordinated tailnet, also set `login-server` to its URL. Set
`advertise-tags` to a comma-separated list when the manually supplied credential
should advertise tags. Relation mode receives both values from
`tailscale-config`.

OAuth client secrets create ephemeral devices by default. Set
`ephemeral=false` to retain the device registration after it goes offline. This
option does not change pre-generated auth keys, whose behavior is fixed when the
key is created.
