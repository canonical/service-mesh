"""Step definitions for relation-provided Tailscale credentials."""

import logging
import os

import jubilant
from pytest_bdd import given, then, when

from integration.helpers import wait_for_active_idle_without_error
from integration.tailscale.helpers import credential_revoked, deploy_charm, get_credential_ids


@given("tailscale-config is deployed in the operator model")
def config_deployed(tailscale_system_juju, terraform_state, credential_info):
    """Deploy the real credential provider without supplying credentials yet."""
    credential_info["provider"] = tailscale_system_juju
    if "tailscale-config" in tailscale_system_juju.status().apps:
        logging.getLogger(__name__).info("Reusing the module's tailscale-config deployment")
    else:
        deploy_charm(tailscale_system_juju, "tailscale-config", terraform_state)


@given("tailscale-config has a granted root credential")
@when("you grant and configure a valid root credential for tailscale-config")
def configure_root(credential_info, root_secrets):
    """Grant the root secret only to tailscale-config using Jubilant."""
    __tracebackhide__ = True
    provider = credential_info["provider"]
    if provider.model not in root_secrets:
        root_secrets[provider.model] = provider.add_secret(
            "tailscale-root",
            {"client-id": os.environ["TAILSCALE_CLIENT_ID"],
             "client-secret": os.environ["TAILSCALE_CLIENT_SECRET"]},
        )
    secret = root_secrets[provider.model]
    provider.grant_secret(secret, "tailscale-config")
    provider.config("tailscale-config", {"root-credential": str(secret)})


@given("tailscale-config has no root credential configured")
def no_root_credential(credential_info):
    """Explicitly establish missing credentials, including on a reused model."""
    provider = credential_info["provider"]
    provider.cli("config", "tailscale-config", "--reset", "root-credential")
    provider.wait(
        lambda status: jubilant.all_blocked(status, "tailscale-config"), timeout=300
    )


@given("tailscale-config is integrated with tailscale-k8s over tailscale-credentials")
@when("you integrate tailscale-config with tailscale-k8s over tailscale-credentials")
def integrate_credentials(tailscale_system_juju, credential_info):
    """Let the real provider mint and distribute a scoped child credential."""
    tailscale_system_juju.integrate(
        "tailscale-k8s:tailscale-credentials", f"{credential_info['remote']}:tailscale-credentials"
    )
    credential_info["related"] = True


@given("tailscale-k8s receives credentials from tailscale-config")
def operator_receives_credentials(tailscale_system_juju, credential_info, root_secrets):
    """Establish working relation-driven credentials before ingress scenarios."""
    if not credential_info["related"]:
        configure_root(credential_info, root_secrets)
        integrate_credentials(tailscale_system_juju, credential_info)
    wait_for_active_idle_without_error([tailscale_system_juju])


@then("tailscale-config has provisioned a credential for tailscale-k8s")
def credential_provisioned(tailscale_system_juju, credential_info):
    """Observe the provider's minted credential and an active operator."""
    provider = credential_info["provider"]
    provider.wait(lambda _: bool(get_credential_ids(provider)), timeout=300, error=jubilant.any_error)
    keys = get_credential_ids(provider)
    assert len(keys) == 1
    assert not credential_revoked(next(iter(keys)))
    credential_info["keys"] = keys
    wait_for_active_idle_without_error([provider, tailscale_system_juju])


@given("tailscale-config has not provisioned a credential for tailscale-k8s")
def credential_not_provisioned(credential_info):
    """Check credential provisioning independently of the running operator's traffic."""
    provider = credential_info["provider"]
    provider.wait(
        lambda _: not get_credential_ids(provider), timeout=300, error=jubilant.any_error
    )


@when("you remove the tailscale-credentials relation between tailscale-config and tailscale-k8s")
def remove_credentials(tailscale_system_juju, credential_info):
    """Remove the consumer relation after its ingress proxies have been removed."""
    credential_info["keys"] = get_credential_ids(credential_info["provider"])
    assert credential_info["keys"], "No provisioned credential to revoke"
    tailscale_system_juju.remove_relation(
        "tailscale-k8s:tailscale-credentials", f"{credential_info['remote']}:tailscale-credentials"
    )
    credential_info["related"] = False


@then("the credential provisioned for tailscale-k8s is revoked on the control server")
def credential_is_revoked(credential_info):
    """Check actual API revocation, not just disappearance from relation data."""
    keys = credential_info["keys"]
    assert keys
    credential_info["provider"].wait(
        lambda _: all(credential_revoked(key) for key in keys), timeout=300, error=jubilant.any_error
    )


@then("tailscale-k8s is blocked")
def operator_blocked(tailscale_system_juju):
    """Wait for the operator to report its missing credential."""
    tailscale_system_juju.wait(
        lambda status: jubilant.all_blocked(status, "tailscale-k8s"), timeout=300
    )
