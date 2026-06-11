# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from helpers import (
    get_auth_policy_spec,
    get_configmap_data,
    get_k8s_service_address,
    get_listener_condition,
    istio_k8s,
    oauth_k8s,
)
from jubilant import Juju, all_active, all_blocked

# Expected default header values — must match DEFAULT_* in lib/charms/istio_k8s/v0/istio_ingress_config.py
EXPECTED_INCLUDE_HEADERS_IN_CHECK = [
    "authorization",
    "cookie",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-uri",
    "x-forwarded-prefix",
]
EXPECTED_HEADERS_TO_DOWNSTREAM_ON_ALLOW = ["set-cookie"]
EXPECTED_HEADERS_TO_DOWNSTREAM_ON_DENY = ["content-type", "set-cookie"]

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
resources = {
    "metrics-proxy-image": METADATA["resources"]["metrics-proxy-image"]["upstream-source"],
}

INGRESS_CONFIG_RELATION = "istio-ingress-config"
FORWARD_AUTH_RELATION = "forward-auth"


@pytest.mark.setup
@pytest.mark.dependency(name="test_deploy_dependencies")
def test_deploy_dependencies(juju: Juju, istio_core_juju: Juju):
    # istio_core_juju fixture deploys istio-k8s in a separate model
    juju.deploy(**asdict(oauth_k8s))
    juju.wait(lambda s: all_active(s, oauth_k8s.app), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_deployment", depends=["test_deploy_dependencies"])
def test_deployment(juju: Juju, istio_ingress_charm, resources):
    juju.deploy(istio_ingress_charm, resources=resources, app=APP_NAME, trust=True)
    juju.wait(lambda s: all_active(s, APP_NAME), timeout=1000, delay=5, successes=3)


@pytest.mark.dependency(name="test_relations_setup", depends=["test_deployment"])
def test_relations_setup(juju: Juju, istio_core_juju: Juju):
    # Create cross-model offer from istio-core for ingress-config
    istio_core_juju.cli(
        "offer",
        f"{istio_core_juju.model}.{istio_k8s.app}:{INGRESS_CONFIG_RELATION}",
        INGRESS_CONFIG_RELATION,
        include_model=False,
    )
    # Consume the offer in the primary model
    juju.cli(
        "consume",
        f"admin/{istio_core_juju.model}.{INGRESS_CONFIG_RELATION}",
    )
    juju.integrate(f"{oauth_k8s.app}:{FORWARD_AUTH_RELATION}", APP_NAME)
    juju.integrate(INGRESS_CONFIG_RELATION, APP_NAME)
    juju.wait(
        lambda s: all_active(s, APP_NAME, oauth_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )
    istio_core_juju.wait(
        lambda s: all_active(s, istio_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )


@pytest.mark.dependency(
    name="test_verify_initial_ext_authz_configuration", depends=["test_relations_setup"]
)
def test_verify_initial_ext_authz_configuration(juju: Juju, istio_core_juju: Juju):
    """Initial configuration verification."""
    policy_name = f"ext-authz-{APP_NAME}"
    assert_config_state(juju, istio_core_juju.model, policy_name)


@pytest.mark.dependency(
    name="test_oauth2_proxy_relation_break_and_recovery", depends=["test_relations_setup"]
)
def test_oauth2_proxy_relation_break_and_recovery(juju: Juju, istio_core_juju: Juju):
    """Test breaking and recovering the oauth2-proxy:forward-auth relation."""
    policy_name = f"ext-authz-{APP_NAME}"

    juju.remove_relation(f"{oauth_k8s.app}:{FORWARD_AUTH_RELATION}", APP_NAME)
    juju.wait(
        lambda s: all_active(s, APP_NAME, oauth_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )
    istio_core_juju.wait(
        lambda s: all_active(s, istio_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )

    # After breaking the relation, expect the policy to be removed and extensionProviders cleared.
    policy_spec = get_auth_policy_spec(juju.model, policy_name)
    assert not policy_spec, f"Expected AuthorizationPolicy '{policy_name}' to be removed."
    mesh_config = load_mesh_config(istio_core_juju.model)
    extension_providers = mesh_config.get("extensionProviders", [])
    assert not extension_providers, "Expected extensionProviders to be empty after relation break."

    # Re-establish the relation and verify the config state.
    juju.integrate(f"{oauth_k8s.app}:{FORWARD_AUTH_RELATION}", APP_NAME)
    juju.wait(
        lambda s: all_active(s, APP_NAME, oauth_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )
    istio_core_juju.wait(
        lambda s: all_active(s, istio_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )

    assert_config_state(juju, istio_core_juju.model, policy_name)


@pytest.mark.dependency(
    name="test_istio_ingress_config_relation_break_and_recovery", depends=["test_relations_setup"]
)
def test_istio_ingress_config_relation_break_and_recovery(juju: Juju, istio_core_juju: Juju):
    """Test breaking and recovering the istio-ingress-config to istio-ingress-k8s relation."""
    policy_name = f"ext-authz-{APP_NAME}"

    juju.remove_relation(INGRESS_CONFIG_RELATION, APP_NAME)

    # After breaking the relation, expect the istio-ingress to be in a blocked state
    juju.wait(lambda s: all_blocked(s, APP_NAME), timeout=1000, delay=5, successes=3)

    # Gateway should be removed and ingress should be disabled
    istio_ingress_address = get_k8s_service_address(juju.model, "istio-ingress-k8s-istio")
    assert not istio_ingress_address, "Expected gateway service to be removed."
    gateway_listener_condition = get_listener_condition(juju.model, APP_NAME)
    assert not gateway_listener_condition, "Expected gateway listener to be removed."

    # Re-establish the relation and verify the config state.
    juju.integrate(INGRESS_CONFIG_RELATION, APP_NAME)
    juju.wait(
        lambda s: all_active(s, APP_NAME, oauth_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )
    istio_core_juju.wait(
        lambda s: all_active(s, istio_k8s.app),
        timeout=1000,
        delay=5,
        successes=3,
    )

    assert_config_state(juju, istio_core_juju.model, policy_name)


def load_mesh_config(model_name: str) -> dict:
    """Load and parse the mesh configuration from the Istio ConfigMap."""
    istio_cm_data = get_configmap_data(model_name, "istio")
    assert istio_cm_data, "Failed to retrieve 'istio' ConfigMap."

    mesh_config_yaml = istio_cm_data.get("mesh")
    assert mesh_config_yaml, "'mesh' key not found in ConfigMap data."
    return yaml.safe_load(mesh_config_yaml)


def get_envoy_authz(mesh_config: dict, provider_name: str) -> dict:
    """Extract the envoyExtAuthzHttp config for the matching provider."""
    extension_providers = mesh_config.get("extensionProviders", [])
    assert extension_providers, "'extensionProviders' not found or empty in mesh config."

    matching_provider = next(
        (p for p in extension_providers if p.get("name") == provider_name), None
    )
    assert matching_provider, f"Provider '{provider_name}' not found in extensionProviders."

    envoy_authz = matching_provider.get("envoyExtAuthzHttp")
    assert envoy_authz, f"envoyExtAuthzHttp config missing for provider '{provider_name}'."
    return envoy_authz


def assert_config_state(juju: Juju, istio_core_model: str, policy_name: str) -> None:
    """Assert that the config state is as expected.

    - AuthorizationPolicy exists with action 'CUSTOM'.
    - The provider exists and its name is present.
    - The Istio mesh config contains an extensionProvider with the proper envoy config.
    - The envoyExtAuthzHttp has a matching provider.
    - All 4 header configurations are present with expected values.
    """
    policy_spec = get_auth_policy_spec(juju.model, policy_name)
    assert policy_spec, f"AuthorizationPolicy '{policy_name}' not found."
    assert policy_spec["action"] == "CUSTOM", f"Unexpected action {policy_spec.get('action')}"

    provider = policy_spec["provider"]
    provider_name = provider.get("name", "")
    assert provider_name, "Provider name missing in policy."

    mesh_config = load_mesh_config(istio_core_model)
    envoy_authz = get_envoy_authz(mesh_config, provider_name)

    expected_service = f"{oauth_k8s.app}.{juju.model}.svc.cluster.local"
    assert envoy_authz.get("service") == expected_service, (
        f"Expected service '{expected_service}', got '{envoy_authz.get('service')}'"
    )

    # Verify header configurations
    assert envoy_authz.get("includeRequestHeadersInCheck") == EXPECTED_INCLUDE_HEADERS_IN_CHECK, (
        f"Expected includeRequestHeadersInCheck '{EXPECTED_INCLUDE_HEADERS_IN_CHECK}', "
        f"got '{envoy_authz.get('includeRequestHeadersInCheck')}'"
    )
    # headersToUpstreamOnAllow may come from oauth2-proxy or use defaults
    headers_to_upstream = envoy_authz.get("headersToUpstreamOnAllow")
    assert headers_to_upstream is not None, "headersToUpstreamOnAllow is missing"
    assert (
        envoy_authz.get("headersToDownstreamOnAllow") == EXPECTED_HEADERS_TO_DOWNSTREAM_ON_ALLOW
    ), (
        f"Expected headersToDownstreamOnAllow '{EXPECTED_HEADERS_TO_DOWNSTREAM_ON_ALLOW}', "
        f"got '{envoy_authz.get('headersToDownstreamOnAllow')}'"
    )
    assert (
        envoy_authz.get("headersToDownstreamOnDeny") == EXPECTED_HEADERS_TO_DOWNSTREAM_ON_DENY
    ), (
        f"Expected headersToDownstreamOnDeny '{EXPECTED_HEADERS_TO_DOWNSTREAM_ON_DENY}', "
        f"got '{envoy_authz.get('headersToDownstreamOnDeny')}'"
    )
