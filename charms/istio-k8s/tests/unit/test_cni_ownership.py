# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import call

import ops
import pytest
from lightkube import ApiError
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.models.rbac_v1 import RoleRef, Subject
from lightkube.resources.core_v1 import ConfigMap, Pod
from lightkube.resources.rbac_authorization_v1 import ClusterRoleBinding
from scenario import Context, Model, State
from scenario.errors import UncaughtCharmError

from src.charm import IstioCoreCharm
from src.cni_ownership import (
    can_recognise,
    expected_cni_binding,
    get_recognised_owner_namespace,
    is_cni_cluster_role_binding,
)


def _binding(
    namespace: str, application: str = "istio", subject_namespace: str | None = None
) -> ClusterRoleBinding:
    binding = expected_cni_binding(application, namespace)
    if subject_namespace:
        binding.subjects = [
            Subject(kind="ServiceAccount", name="istio-cni", namespace=subject_namespace)
        ]
    return binding


def _api_error(code: int, reason: str) -> ApiError:
    return ApiError(status={"code": code, "reason": reason, "message": reason})


@pytest.fixture
def cni_context(mocker):
    for method in (
        "_publish_ext_authz_provider_names",
        "_publish_istio_metadata",
        "_reconcile_gateway_api_crds",
        "_reconcile_istio_crds",
        "_reconcile_authorization_policies",
        "_reconcile_control_plane",
        "_set_istio_version",
        "_setup_proxy_pebble_service",
    ):
        mocker.patch.object(IstioCoreCharm, method)
    mocker.patch.object(
        IstioCoreCharm, "_get_control_plane_statuses", return_value=[ops.ActiveStatus()]
    )
    client = mocker.patch("src.charm.Client", autospec=True).return_value
    client.get.return_value = _binding("owner")
    return Context(IstioCoreCharm, app_name="istio"), client


def test_owner_can_reconcile(cni_context, mocker):
    context, client = cni_context
    reconcile = mocker.patch.object(IstioCoreCharm, "_reconcile_control_plane")

    out = context.run(
        context.on.config_changed(), State(leader=True, model=Model(name="owner"))
    )

    assert out.unit_status == ops.ActiveStatus()
    client.create.assert_called_once()
    reconcile.assert_called_once()


def test_existing_owner_can_reconcile(cni_context, mocker):
    context, client = cni_context
    client.create.side_effect = _api_error(409, "AlreadyExists")
    reconcile = mocker.patch.object(IstioCoreCharm, "_reconcile_control_plane")

    context.run(context.on.start(), State(leader=True, model=Model(name="owner")))

    client.get.assert_called()
    reconcile.assert_called_once()


@pytest.mark.parametrize(
    "binding",
    [
        _binding("other-model"),
        _binding("owner", application="other-app"),
        _binding("owner", subject_namespace="other-model"),
        ClusterRoleBinding(
            metadata=ObjectMeta(name="istio-cni"),
            roleRef=_binding("owner").roleRef,
            subjects=_binding("owner").subjects,
        ),
    ],
    ids=[
        "other-namespace",
        "other-application",
        "mismatched-subject",
        "unrecognized-binding",
    ],
)
def test_contender_is_blocked_without_reconciling(cni_context, mocker, binding):
    context, client = cni_context
    client.create.side_effect = _api_error(409, "AlreadyExists")
    client.get.return_value = binding
    reconcile = mocker.patch.object(IstioCoreCharm, "_reconcile_control_plane")

    out = context.run(context.on.config_changed(), State(leader=True, model=Model(name="owner")))

    assert out.unit_status.name == "blocked"
    client.patch.assert_not_called()
    client.delete.assert_not_called()
    reconcile.assert_not_called()


def test_claim_api_errors_are_not_hidden(cni_context):
    context, client = cni_context
    error = _api_error(403, "Forbidden")
    client.create.side_effect = error

    with pytest.raises(UncaughtCharmError) as caught:
        context.run(context.on.start(), State(leader=True, model=Model(name="owner")))

    assert caught.value.__cause__ is error


def test_disappearing_claim_waits_for_another_attempt(cni_context, mocker):
    context, client = cni_context
    client.create.side_effect = _api_error(409, "AlreadyExists")
    client.get.side_effect = _api_error(404, "NotFound")
    reconcile = mocker.patch.object(IstioCoreCharm, "_reconcile_control_plane")

    out = context.run(context.on.start(), State(leader=True, model=Model(name="owner")))

    assert out.unit_status == ops.WaitingStatus("Waiting to claim Istio CNI ownership")
    reconcile.assert_not_called()


def test_update_status_retries_claim(cni_context, mocker):
    context, client = cni_context
    reconcile = mocker.patch.object(IstioCoreCharm, "_reconcile_control_plane")

    context.run(context.on.update_status(), State(leader=True, model=Model(name="owner")))

    client.create.assert_called_once()
    reconcile.assert_called_once()


def test_removing_contender_cleans_its_resources_without_deleting_shared_claim(cni_context, mocker):
    context, client = cni_context
    client.get.return_value = _binding("other-model")
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.return_value = []

    context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert manager.get_deployed_resources.call_count == 3
    client.delete.assert_not_called()


def test_removing_after_claim_disappears_cleans_resources(cni_context, mocker):
    context, client = cni_context
    client.get.side_effect = _api_error(404, "NotFound")
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.side_effect = [
        [ConfigMap(metadata=ObjectMeta(name="owned-config", namespace="owner"))],
        [],
        [],
    ]

    context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert client.delete.call_args_list == [
        call(res=ConfigMap, name="owned-config", namespace="owner"),
    ]
    assert manager.get_deployed_resources.call_count == 3


def test_owner_releases_claim_after_cleaning_resources_and_pods(cni_context, mocker):
    context, client = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.side_effect = [
        [
            _binding("owner"),
            ConfigMap(metadata=ObjectMeta(name="owned-config", namespace="owner")),
        ],
        [],
        [],
    ]
    client.list.return_value = []

    context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert client.delete.call_args_list == [
        call(res=ConfigMap, name="owned-config", namespace="owner"),
        call(ClusterRoleBinding, "istio-cni"),
    ]
    assert manager.get_deployed_resources.call_count == 3


def test_owner_waits_for_pod_shutdown_before_releasing_claim(cni_context, mocker):
    context, client = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.return_value = []
    client.list.side_effect = [
        [Pod(metadata=ObjectMeta(name="istio-cni-node", namespace="owner"))],
        [],
    ]
    sleep = mocker.patch("src.charm.time.sleep")

    context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert sleep.call_args_list == [call(1)]
    client.delete.assert_called_once_with(ClusterRoleBinding, "istio-cni")


def test_failed_cleanup_keeps_claim(cni_context, mocker):
    context, client = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.side_effect = _api_error(500, "InternalError")

    with pytest.raises(UncaughtCharmError):
        context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    client.delete.assert_not_called()


def test_shutdown_timeout_keeps_claim(cni_context, mocker):
    context, client = cni_context
    manager = mocker.patch.object(IstioCoreCharm, "_get_resource_manager").return_value
    manager.get_deployed_resources.return_value = []
    client.list.return_value = [Pod(metadata=ObjectMeta(name="istiod", namespace="owner"))]
    mocker.patch("src.charm.CONTROL_PLANE_TERMINATION_TIMEOUT", 0)

    with pytest.raises(UncaughtCharmError) as caught:
        context.run(context.on.remove(), State(leader=True, model=Model(name="owner")))

    assert isinstance(caught.value.__cause__, TimeoutError)
    client.delete.assert_not_called()


@pytest.mark.parametrize(
    "resource,expected",
    [
        (_binding("owner"), True),
        (
            ClusterRoleBinding(
                metadata=ObjectMeta(name="other-binding"), roleRef=_binding("owner").roleRef
            ),
            False,
        ),
        (ClusterRoleBinding(metadata=None, roleRef=_binding("owner").roleRef), False),
        (ConfigMap(metadata=ObjectMeta(name="istio-cni", namespace="owner")), False),
    ],
    ids=["cni-binding", "other-binding", "no-metadata", "other-resource-type"],
)
def test_is_cni_cluster_role_binding(resource, expected):
    assert is_cni_cluster_role_binding(resource) is expected


def test_expected_cni_binding_shape():
    assert expected_cni_binding("my-app", "my-model") == ClusterRoleBinding(
        metadata=ObjectMeta(
            name="istio-cni",
            labels={
                "app.kubernetes.io/instance": "my-model-my-app",
                "kubernetes-resource-handler-scope": "control-plane",
            },
        ),
        roleRef=RoleRef(
            apiGroup="rbac.authorization.k8s.io", kind="ClusterRole", name="istio-cni"
        ),
        subjects=[Subject(kind="ServiceAccount", name="istio-cni", namespace="my-model")],
    )


def test_get_recognised_owner_namespace_returns_subject_namespace():
    assert get_recognised_owner_namespace(_binding("other-model")) == "other-model"


def test_get_recognised_owner_namespace_rejects_wrong_role():
    binding = _binding("other-model")
    binding.roleRef = RoleRef(
        apiGroup="rbac.authorization.k8s.io", kind="ClusterRole", name="other-role"
    )
    assert get_recognised_owner_namespace(binding) is None


@pytest.mark.parametrize(
    "subjects",
    [
        [],
        [
            Subject(kind="ServiceAccount", name="istio-cni", namespace="other-model"),
            Subject(kind="ServiceAccount", name="istio-cni", namespace="other-model"),
        ],
    ],
    ids=["no-subjects", "multiple-subjects"],
)
def test_get_recognised_owner_namespace_rejects_non_single_subject(subjects):
    binding = _binding("other-model")
    binding.subjects = subjects
    assert get_recognised_owner_namespace(binding) is None


@pytest.mark.parametrize(
    "subject",
    [
        Subject(kind="User", name="istio-cni", namespace="other-model"),
        Subject(kind="ServiceAccount", name="other-account", namespace="other-model"),
    ],
    ids=["wrong-kind", "wrong-name"],
)
def test_get_recognised_owner_namespace_rejects_unexpected_subject(subject):
    binding = _binding("other-model")
    binding.subjects = [subject]
    assert get_recognised_owner_namespace(binding) is None


@pytest.mark.parametrize(
    "binding",
    [
        _binding("other-model"),
        _binding("owner", application="other-app"),
        _binding("owner", subject_namespace="other-model"),
    ],
    ids=["other-namespace", "other-application", "other-subject-namespace"],
)
def test_can_recognise_other_installations_claims(binding):
    assert can_recognise(binding)


def test_can_recognise_rejects_wrong_role():
    binding = _binding("other-model")
    binding.roleRef = RoleRef(
        apiGroup="rbac.authorization.k8s.io", kind="ClusterRole", name="other-role"
    )
    assert not can_recognise(binding)


@pytest.mark.parametrize(
    "subjects",
    [
        [],
        [
            Subject(kind="ServiceAccount", name="istio-cni", namespace="other-model"),
            Subject(kind="ServiceAccount", name="istio-cni", namespace="other-model"),
        ],
    ],
    ids=["no-subjects", "multiple-subjects"],
)
def test_can_recognise_rejects_non_single_subject(subjects):
    binding = _binding("other-model")
    binding.subjects = subjects
    assert not can_recognise(binding)


@pytest.mark.parametrize(
    "subject",
    [
        Subject(kind="User", name="istio-cni", namespace="other-model"),
        Subject(kind="ServiceAccount", name="other-account", namespace="other-model"),
        Subject(kind="ServiceAccount", name="istio-cni"),
    ],
    ids=["wrong-kind", "wrong-name", "no-namespace"],
)
def test_can_recognise_rejects_unexpected_subject(subject):
    binding = _binding("other-model")
    binding.subjects = [subject]
    assert not can_recognise(binding)


def test_can_recognise_rejects_missing_instance_label():
    binding = _binding("other-model")
    del binding.metadata.labels["app.kubernetes.io/instance"]
    assert not can_recognise(binding)


def test_can_recognise_rejects_wrong_scope_label():
    binding = _binding("other-model")
    binding.metadata.labels["kubernetes-resource-handler-scope"] = "other-scope"
    assert not can_recognise(binding)
