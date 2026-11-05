# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Ownership checks for the shared Istio CNI ClusterRoleBinding.

Independent Istio installations on one cluster share ClusterRoleBinding/istio-cni.
The first installation to create the binding owns it; these functions decide
whether an existing binding is a live claim held by a given installation.
"""

from canonical_service_mesh.k8s.resource_manager import create_charm_default_labels
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.models.rbac_v1 import RoleRef, Subject
from lightkube.resources.rbac_authorization_v1 import ClusterRoleBinding

CONTROL_PLANE_LABEL = "control-plane"
CNI_CLUSTER_ROLE_BINDING = "istio-cni"

_CNI_CLUSTER_ROLE = "istio-cni"
_CNI_SERVICE_ACCOUNT = "istio-cni"

_INSTANCE_LABEL = "app.kubernetes.io/instance"
_SCOPE_LABEL = "kubernetes-resource-handler-scope"

# Comparison reference only; expected_cni_binding builds a fresh RoleRef per claim.
_EXPECTED_ROLE_REF = RoleRef(
    apiGroup="rbac.authorization.k8s.io", kind="ClusterRole", name=_CNI_CLUSTER_ROLE
)


def expected_cni_binding(app_name: str, namespace: str) -> ClusterRoleBinding:
    """Build the ClusterRoleBinding an istio-k8s installation expects to claim."""
    return ClusterRoleBinding(
        metadata=ObjectMeta(
            name=CNI_CLUSTER_ROLE_BINDING,
            labels=create_charm_default_labels(app_name, namespace, scope=CONTROL_PLANE_LABEL),
        ),
        roleRef=RoleRef(
            apiGroup="rbac.authorization.k8s.io",
            kind="ClusterRole",
            name=_CNI_CLUSTER_ROLE,
        ),
        subjects=[
            Subject(
                kind="ServiceAccount",
                name=_CNI_SERVICE_ACCOUNT,
                namespace=namespace,
            )
        ],
    )


def can_recognise(binding: ClusterRoleBinding) -> bool:
    """Return True if the binding is recognisably a claim held by an istio-k8s charm.

    Recognition does not imply ownership by this installation: label values may
    name any application or model. The claim must still grant the expected CNI
    role to a single CNI ServiceAccount in some namespace, and carry the
    control-plane resource-handler labels.
    """
    labels = (binding.metadata.labels or {}) if binding.metadata else {}
    return (
        identify_owner_namespace(binding) is not None
        and bool(labels.get(_INSTANCE_LABEL))
        and labels.get(_SCOPE_LABEL) == CONTROL_PLANE_LABEL
    )


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


def identify_owner_namespace(binding: ClusterRoleBinding) -> str | None:
    """Return the owning installation's namespace, or None if the owner cannot be identified.

    Only a claim with this charm's shape (expected role, expected ServiceAccount)
    reliably names another Istio installation in its subject's namespace.
    """
    if binding.roleRef != _EXPECTED_ROLE_REF:
        return None
    subject = _sole_cni_subject(binding)
    if subject is None:
        return None
    return subject.namespace


def _sole_cni_subject(binding: ClusterRoleBinding) -> Subject | None:
    """Return the binding's only subject if it is the expected CNI ServiceAccount.

    The subject's namespace names the claiming installation, so it is the one
    field allowed to differ between installations.
    """
    subjects = binding.subjects or []
    if len(subjects) != 1:
        return None
    (subject,) = subjects
    if subject.kind != "ServiceAccount" or subject.name != _CNI_SERVICE_ACCOUNT:
        return None
    return subject
