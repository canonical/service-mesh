# Tailscale solution tests

This suite exercises `tailscale-config`, `tailscale-k8s`, and
`tailscale-beacon-k8s` together with Bookinfo productpage and details. It uses
Terraform application deployments, Jubilant, and pytest-bdd, like the Istio
solution suite. It is separate from each charm's integration tests.

The initial backend is Tailscale SaaS. Headscale is not enabled in this suite:
the credential provider's Headscale backend and a compatible Headscale charm
are prerequisites for running the same solution scenarios against it.

## Prerequisites

Use a dedicated, non-production tailnet and a disposable Kubernetes cluster
with a bootstrapped Juju controller. The controller and `kubectl` must target
the same cluster, with no existing Tailscale operator. The suite deploys trusted
charms and creates and removes temporary models and tailnet resources.
Install `uv`, Juju, `kubectl`, Terraform or OpenTofu, and the Tailscale snap.
For local runs, explicitly enroll the test machine in that tailnet beforehand.
The suite requires `tailscale status --json` to report a running client and
uses ordinary `curl` with MagicDNS. It never enrolls, reconfigures, or logs out
your local machine.

Configure MagicDNS and the tailnet's tag ownership and access policy before
running the suite. The policy must permit the test client to reach the proxy
devices on ports 80 and 8080. Policy management is not part of the tests.

Provide `TAILSCALE_CLIENT_ID` and `TAILSCALE_CLIENT_SECRET` through your secret
manager or shell environment, not source files or command-line arguments. This
root OAuth client needs `oauth_keys`, `auth_keys`, and `devices:core` with the
permissions required to mint and revoke child credentials and manage test
devices. Its tags must match the operator tags, which must own the proxy tags.
Only `tailscale-config` receives this root credential as a Juju secret; the
operator receives a child credential through its relation.

## Running

From `tests/`, the following commands require no tailnet credentials and do not
deploy infrastructure:

```sh
uvx tox -e tailscale-collect,tailscale-terraform
```

Run the solution against the published development charms:

```sh
uvx tox -e tailscale
uvx tox -e tailscale -- -k test_ingress.py
```

The deployment default is `TAILSCALE_CHANNEL=dev/edge`; the Bookinfo applications
use `latest/stable`. The suite's Terraform roots reference local reusable charm
modules, so module changes are exercised without first publishing this repository.
The charms themselves are deployed from Charmhub, not packed from the checkout.

Each scenario gets a fresh operator model through `jubilant.temp_model()`;
pytest-jubilant manages the module-scoped workload models. Feature loaders remain
one file per feature. This avoids depending on credential hot-reloading between
scenarios without restarting the operator inside a scenario.

Use `--juju-controller` and `--juju-cloud` to select the deployment target, keeping
`kubectl` pointed at that same cluster. Terraform uses the selected model UUID and
the logged-in Juju CLI account; it does not assume an `admin` model owner or use
separate controller credentials from the environment.

## CI credentials

The `Tests: Tailscale Solution` workflow can be dispatched manually. Configure a
GitHub environment named `tailscale-solution-tests` with the test-tailnet secrets,
required reviewers, and deployment-branch restrictions appropriate for trusted
code. Do not grant these credentials to unreviewed branches.

Also configure `TAILSCALE_TEST_AUTH_KEY` as a **reusable, ephemeral, tagged**
auth key for the runner client. Pre-approve it if device approval is enabled.
Use a client-only tag allowed to access the proxy ports, and renew this key
before it expires. It is independent of the root OAuth credential given to
`tailscale-config`.

CI installs the Tailscale snap on the disposable runner VM, joins with this
auth key, and always attempts `tailscale logout` afterward. Logout removes
the ephemeral client. There is no client pod, SOCKS proxy, or enrollment module.

Set the repository variable `RUN_TAILSCALE_SOLUTION_TESTS=true` to enable
secret-dependent same-repository PR and scheduled runs. Fork PRs only run the
offline checks, and the solution workflow rejects `pull_request_target` execution.
An enabled solution run fails if its required credentials are missing.
Live runs are serialized to limit resource contention in the shared test tailnet.

Credential loss is treated as non-disruptive to existing traffic: a Blocked
operator is not required to stop, and missing root credentials do not imply
that an existing ingress URL disappears. Credential scenarios assert child
credential provisioning/revocation and charm status, without forcing operator
restarts. Ingress withdrawal is tested separately by removing the ingress relation.

The suite must remove ingress proxies while the operator still has working
credentials, then revoke its child credentials and remove its models and
run-owned devices. Forced workflow cancellation or runner loss can interrupt
cleanup; remove only that run's remaining resources in the dedicated test
tailnet. Never publish raw secrets, Terraform state, or unredacted diagnostic
logs as workflow artifacts.

If any ingress cleanup fails, the suite attempts the remaining ingress removals,
reports all failures, and stops before another scenario. It does not explicitly
revoke credentials or delete devices while ingress remains. Normal model teardown
still runs; inspect the reported resources and tailnet for leftovers before rerunning.
