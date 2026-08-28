# Contributing
![GitHub License](https://img.shields.io/github/license/canonical/service-mesh)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/service-mesh)
![GitHub Issues](https://img.shields.io/github/issues/canonical/service-mesh)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/service-mesh)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/service-mesh)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/service-mesh?style=social)

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
