# Contributing
![GitHub License](https://img.shields.io/github/license/canonical/kiali-k8s-operator)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/kiali-k8s-operator)
![GitHub Issues](https://img.shields.io/github/issues/canonical/kiali-k8s-operator)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/kiali-k8s-operator)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/kiali-k8s-operator)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/kiali-k8s-operator?style=social)

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
tox run -e format        # update your code according to linting rules
tox run -e lint          # code style
tox run -e static        # static type checking
tox run -e unit          # unit tests
tox run -e scenario      # scenario tests
tox run -e integration   # integration tests
tox                      # runs 'format', 'lint', 'static', 'unit', 'scenario', and 'integration' environments
```

## Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```
