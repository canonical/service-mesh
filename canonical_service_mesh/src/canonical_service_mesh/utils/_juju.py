# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Juju identity utilities for service mesh."""


def get_peer_identity_for_juju_application(app_name: str, namespace: str) -> str:
    """Return a Juju application's peer identity.

    Format is defined by ``principals`` in the Istio AuthorizationPolicy Source reference.
    Relies on the Juju convention that each application gets a ServiceAccount of the same name.

    Args:
        app_name: The name of the Juju application.
        namespace: The Kubernetes namespace of the application.

    Returns:
        The SPIFFE identity string for the application.
    """
    return get_peer_identity_for_service_account(app_name, namespace)


def get_peer_identity_for_service_account(service_account: str, namespace: str) -> str:
    """Return a ServiceAccount's peer identity.

    Format: ``cluster.local/ns/{namespace}/sa/{service_account}``

    Args:
        service_account: The Kubernetes ServiceAccount name.
        namespace: The Kubernetes namespace.

    Returns:
        The SPIFFE identity string for the service account.
    """
    return f"cluster.local/ns/{namespace}/sa/{service_account}"
