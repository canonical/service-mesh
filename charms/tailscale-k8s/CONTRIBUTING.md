# Contributing
![GitHub License](https://img.shields.io/github/license/canonical/tailscale-k8s-operator)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/tailscale-k8s-operator)
![GitHub Issues](https://img.shields.io/github/issues/canonical/tailscale-k8s-operator)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/tailscale-k8s-operator)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/tailscale-k8s-operator)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/tailscale-k8s-operator?style=social)

## Development environment

To make contributions to this charm, you'll need a working [development setup](https://juju.is/docs/sdk/dev-setup).

You can create an environment for development with `tox`:

```shell
tox devenv -e integration
source venv/bin/activate
```

## Testing

This project uses `tox` for managing test environments. There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

```shell
tox run -e fmt           # update your code according to linting rules
tox run -e lint          # code style
tox run -e static        # static type checking
tox run -e unit          # unit tests
tox run -e integration   # integration tests
tox                      # runs 'lint', 'static', and 'unit' environments
```

## Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```
