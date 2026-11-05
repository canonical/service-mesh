# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Ownership checks for the shared Istio CNI ClusterRoleBinding.

Independent Istio installations on one cluster share ClusterRoleBinding/istio-cni.
The first installation to create the binding owns it; these functions decide
whether an existing binding is a live claim held by a given installation.
"""

from lightkube.models.rbac_v1 import Subject
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


def identify_owner_namespace(
    binding: ClusterRoleBinding, expected: ClusterRoleBinding
) -> str | None:
    """Return the owning installation's namespace, or None if the owner cannot be identified.

    Only a claim with this charm's shape (expected role, expected ServiceAccount)
    reliably names another Istio installation in its subject's namespace.
    """
    if not _binds_expected_role(binding, expected):
        return None
    subject = _sole_expected_subject(binding, expected)
    if subject is None:
        return None
    return subject.namespace


def _binds_expected_role(binding: ClusterRoleBinding, expected: ClusterRoleBinding) -> bool:
    """Check that the claim points at the expected CNI ClusterRole."""
    return binding.roleRef == expected.roleRef


def _sole_expected_subject(
    binding: ClusterRoleBinding, expected: ClusterRoleBinding
) -> Subject | None:
    """Return the binding's only subject if it is the expected CNI ServiceAccount.

    The subject's namespace names the claiming installation, so it is the one
    field allowed to differ from the expected claim.
    """
    subjects = binding.subjects or []
    expected_subjects = expected.subjects or []
    if len(subjects) != 1 or len(expected_subjects) != 1:
        return None
    subject, expected_subject = subjects[0], expected_subjects[0]
    if subject.kind != expected_subject.kind or subject.name != expected_subject.name:
        return None
    return subject
