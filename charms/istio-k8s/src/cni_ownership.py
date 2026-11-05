# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Ownership checks for the shared Istio CNI ClusterRoleBinding.

Independent Istio installations on one cluster share ClusterRoleBinding/istio-cni.
The first installation to create the binding owns it; these functions decide
whether an existing binding is a live claim held by a given installation.
"""

from lightkube.resources.rbac_authorization_v1 import ClusterRoleBinding


def is_owned_by(binding: ClusterRoleBinding, expected: ClusterRoleBinding) -> bool:
    """Return True if the binding is a live claim held by the expected installation.

    Ownership requires the claim to be alive, labelled for the expected
    installation, and still granting the expected CNI access.
    """
    return (
        _is_live_claim(binding)
        and _has_expected_labels(binding, expected)
        and _grants_expected_access(binding, expected)
    )


def _is_live_claim(binding: ClusterRoleBinding) -> bool:
    """Check that the claim exists and is not being deleted."""
    return bool(binding.metadata and not binding.metadata.deletionTimestamp)


def _has_expected_labels(binding: ClusterRoleBinding, expected: ClusterRoleBinding) -> bool:
    """Check that the binding carries all of the expected installation's labels."""
    actual = (binding.metadata.labels or {}) if binding.metadata else {}
    expected_labels = (expected.metadata.labels or {}) if expected.metadata else {}
    return all(actual.get(key) == value for key, value in expected_labels.items())


def _grants_expected_access(binding: ClusterRoleBinding, expected: ClusterRoleBinding) -> bool:
    """Check that the binding still points at the expected CNI role and service account."""
    return binding.subjects == expected.subjects and binding.roleRef == expected.roleRef
