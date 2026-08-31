# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes resource definitions for the Tailscale K8s operator charm.

Builds the lightkube resource objects required by the upstream Tailscale
operator. The objects are applied/garbage-collected by a
KubernetesResourceManager (see charm.py); this module only *describes* them.

Two resource groups (KRM scopes) are managed:
- "operator-resources": ServiceAccount/Role/RoleBinding 'proxies' + the
  'tailscale' IngressClass.
- "crds": the Tailscale CRDs (connectors, dnsconfigs, proxyclasses,
  proxygrouppolicies, proxygroups, recorders, tailnets), loaded from src/crds/.
"""

import logging
from pathlib import Path
from typing import Optional

from lightkube import Client, codecs
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_global_resource
from lightkube.models.meta_v1 import ObjectMeta, OwnerReference
from lightkube.models.rbac_v1 import PolicyRule, RoleRef, Subject
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import Namespace, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding

LOGGER = logging.getLogger(__name__)

# Upstream operator hardcoded names
PROXIES_SA_NAME = "proxies"
INGRESS_CLASS_NAME = "tailscale"

# KubernetesResourceManager scopes (used to build label selectors for GC).
SCOPE_OPERATOR = "operator-resources"
SCOPE_CRDS = "crds"

CRDS_DIR = Path(__file__).parent / "crds"

IngressClass = create_global_resource(
    group="networking.k8s.io",
    version="v1",
    kind="IngressClass",
    plural="ingressclasses",
)

# Resource types each KRM is allowed to manage (used for validation + GC listing).
OPERATOR_RESOURCE_TYPES = {ServiceAccount, Role, RoleBinding, IngressClass}
CRD_RESOURCE_TYPES = {CustomResourceDefinition}


def get_namespace_owner_reference(
    client: Client, namespace: str
) -> Optional[OwnerReference]:
    """Build an OwnerReference to the model's Namespace, for GC of the IngressClass.

    Background: the IngressClass is a *cluster-scoped* resource (see
    `kubectl api-resources`: ingressclasses NAMESPACED=false — this is intrinsic
    to the networking.k8s.io/v1 API and cannot be changed). Juju automatically
    garbage-collects the *namespaced* resources a charm creates (its model
    operator runs a namespace-scoped admission webhook that stamps
    `app.kubernetes.io/managed-by=juju` on them and GCs them on removal), but
    that webhook cannot touch cluster-scoped objects. So without help, the
    IngressClass leaks whenever charm teardown does not run (most notably
    `juju destroy-model --force`, which skips hooks).

    Fix: set an OwnerReference from the IngressClass to the model's Namespace.
    A cluster-scoped dependent may be owned by a cluster-scoped owner (Namespace
    is cluster-scoped), so the Kubernetes garbage collector will delete the
    IngressClass automatically whenever the namespace is deleted — which is
    exactly what `destroy-model` does (including `--force`). This complements
    the reconcile teardown (planned_units == 0 -> KRM.delete), which handles the
    normal `remove-application` case where the namespace is retained.

    We deliberately owner-ref the *Namespace* rather than the app's
    ClusterRoleBinding: "a model maps to a namespace named after the model" is a
    stable, documented Juju-on-Kubernetes guarantee, whereas the per-app
    ClusterRoleBinding (`{model}-{app}`) is a Juju *internal* implementation
    detail (juju/juju internal/provider/kubernetes) with no stability contract.

    Returns None if the namespace can't be read, in which case the IngressClass
    is created without an owner-ref and cleanup falls back to the reconcile
    teardown.

    Args:
        client: A lightkube Client.
        namespace: The model namespace name.
    """
    try:
        ns = client.get(Namespace, name=namespace)
    except ApiError as e:
        LOGGER.warning("Could not read namespace %s for owner reference: %s", namespace, e)
        return None

    uid = ns.metadata.uid if ns.metadata else None
    if not uid:
        return None

    return OwnerReference(
        apiVersion="v1",
        kind="Namespace",
        name=namespace,
        uid=uid,
        # Don't block namespace deletion on this dependent, and this object is
        # not "controlled" by the namespace in the controller-owns sense.
        blockOwnerDeletion=False,
        controller=False,
    )


def build_operator_resources(
    namespace: str, ingressclass_owner: Optional[OwnerReference] = None
) -> list:
    """Build the operator-support resources (proxies SA/RBAC + IngressClass).

    Labels are added by the KubernetesResourceManager at apply time, so they are
    intentionally omitted here.

    Args:
        namespace: The namespace to create the namespaced resources in.
        ingressclass_owner: Optional OwnerReference to attach to the (cluster-
            scoped) IngressClass so the Kubernetes garbage collector cleans it up
            when the owner (the model Namespace) is deleted. See
            `get_namespace_owner_reference` for the full rationale. The namespaced
            resources (SA/Role/RoleBinding) get no owner-ref: Juju already GCs
            them, and cluster->namespaced owner-refs are invalid anyway.
    """
    sa = ServiceAccount(metadata=ObjectMeta(name=PROXIES_SA_NAME, namespace=namespace))

    role = Role(
        metadata=ObjectMeta(name=PROXIES_SA_NAME, namespace=namespace),
        rules=[
            PolicyRule(
                apiGroups=[""],
                resources=["secrets"],
                verbs=["create", "get", "list", "watch", "update", "patch", "delete"],
            ),
            PolicyRule(
                apiGroups=[""],
                resources=["events"],
                verbs=["create", "get", "list", "watch", "patch"],
            ),
        ],
    )

    role_binding = RoleBinding(
        metadata=ObjectMeta(name=PROXIES_SA_NAME, namespace=namespace),
        roleRef=RoleRef(
            apiGroup="rbac.authorization.k8s.io",
            kind="Role",
            name=PROXIES_SA_NAME,
        ),
        subjects=[
            Subject(kind="ServiceAccount", name=PROXIES_SA_NAME, namespace=namespace)
        ],
    )

    # The IngressClass is cluster-scoped, so Juju won't GC it; attach the
    # Namespace owner-ref (when available) as a Kubernetes-native cleanup safety
    # net for `destroy-model` (incl. `--force`, which skips hooks).
    ingress_class = IngressClass(
        metadata=ObjectMeta(
            name=INGRESS_CLASS_NAME,
            ownerReferences=[ingressclass_owner] if ingressclass_owner else None,
        ),
        spec={"controller": "tailscale.com/ts-ingress"},
    )

    return [sa, role, role_binding, ingress_class]


def build_crd_resources() -> list:
    """Load the Tailscale CRDs bundled in src/crds/ as lightkube resources."""
    resources = []
    for crd_file in sorted(CRDS_DIR.glob("*.yaml")):
        resources.extend(codecs.load_all_yaml(crd_file.read_text()))
    return resources


def detect_existing_operator(client: Client, instance_label: str) -> bool:
    """Detect if another Tailscale operator is already running on the cluster.

    Checks whether the cluster-scoped IngressClass 'tailscale' exists and belongs
    to a different charm instance (i.e. its instance label does not match ours).

    Args:
        client: A lightkube Client.
        instance_label: This charm's expected `app.kubernetes.io/instance` label.

    Returns:
        True if a foreign operator is detected, False otherwise.
    """
    try:
        existing = client.get(IngressClass, name=INGRESS_CLASS_NAME)
    except ApiError as e:
        if e.status.code == 404:
            return False
        LOGGER.warning("Error checking for existing operator: %s", e)
        return False

    metadata = existing.metadata
    if metadata is None:
        labels = {}
    elif isinstance(metadata, dict):
        labels = metadata.get("labels") or {}
    else:
        labels = metadata.labels or {}

    return labels.get("app.kubernetes.io/instance") != instance_label
