# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import typing
from unittest.mock import MagicMock, patch

import pytest
import scenario
from canonical_service_mesh.utils.istio import reconcile_charm_labels
from charmlibs.interfaces.service_mesh import (
    AppPolicy,
    Endpoint,
    MeshType,
    Policy,
    ServiceMeshConsumer,
    ServiceMeshProviderAppData,
    UnitPolicy,
)
from httpx import HTTPStatusError, Request, Response
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import ConfigMap, Service
from ops import CharmBase


def consumer_context(policies: typing.List[typing.Union[Policy, AppPolicy, UnitPolicy]]) -> scenario.Context:
    meta = {
        "name": "consumer-charm",
        "requires": {
            "service-mesh": {"interface": "service_mesh"},
            "require-cmr-mesh": {"interface": "cross_model_mesh"},
            "rela": {"interface": "foo"},
            "relb": {"interface": "foo"},
        },
        "provides": {
            "provide-cmr-mesh": {"interface": "cross_model_mesh"},
            "relc": {"interface": "foo"},
            "reld": {"interface": "foo"},
        },
    }

    class ConsumerCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.mesh = ServiceMeshConsumer(charm=self, policies=policies)

    return scenario.Context(ConsumerCharm, meta)


ENDPOINT_A = Endpoint(hosts=[], ports=[80], methods=[], paths=[])

WITH_COMPLEX_ENDPOINTS = (
    [
        AppPolicy(
            relation="rela",
            endpoints=[
                Endpoint(
                    hosts=["localhost"],
                    ports=[443, 9000],
                    methods=["GET", "POST"],  # type: ignore
                    paths=["/metrics", "/data"],
                ),
                Endpoint(
                    hosts=["example.com"],
                    ports=[3000],
                    methods=["DELETE"],  # type: ignore
                    paths=["/foobar"],
                ),
            ],
            service=None,
        )
    ],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [
                {
                    "hosts": ["localhost"],
                    "ports": [443, 9000],
                    "methods": ["GET", "POST"],
                    "paths": ["/metrics", "/data"],
                },
                {
                    "hosts": ["example.com"],
                    "ports": [3000],
                    "methods": ["DELETE"],
                    "paths": ["/foobar"],
                },
            ],
        }
    ],
)

MULTIPLE_POLICIES = (
    [
        AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None),
        AppPolicy(relation="relc", endpoints=[ENDPOINT_A], service=None),
    ],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        },
        {
            "source_app_name": "remote_c",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        },
    ],
)

REQUIRER = (
    [AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

REQUIRER_CMR = (
    [AppPolicy(relation="relb", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_b",
            "source_namespace": "remote_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

PROVIDER = (
    [AppPolicy(relation="relc", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_c",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

PROVIDER_CMR = (
    [AppPolicy(relation="reld", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_d",
            "source_namespace": "remote_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

# Test case for deprecated Policy class (should work like AppPolicy)
POLICY_DEPRECATED = (
    [Policy(relation="rela", endpoints=[ENDPOINT_A], service=None)],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "app",
            "endpoints": [{"hosts": [], "ports": [80], "methods": [], "paths": []}],
        }
    ],
)

UNIT_POLICY = (
    [UnitPolicy(relation="rela", ports=[8080])],
    [
        {
            "source_app_name": "remote_a",
            "source_namespace": "my_model",
            "target_app_name": "consumer-charm",
            "target_namespace": "my_model",
            "target_selector_labels": None,
            "target_service": None,
            "target_type": "unit",
            "endpoints": [{"hosts": None, "ports": [8080], "methods": None, "paths": None}],
        }
    ],
)

POLICY_DATA_PARAMS = [
    WITH_COMPLEX_ENDPOINTS,
    MULTIPLE_POLICIES,
    REQUIRER,
    REQUIRER_CMR,
    PROVIDER,
    PROVIDER_CMR,
    POLICY_DEPRECATED,
    UNIT_POLICY,
]


@pytest.mark.parametrize("policies,expected_data", POLICY_DATA_PARAMS)
def test_relation_data_policies(policies, expected_data):
    """Test that a given list of policies produces the expected output.

    This test sets up 4 relations; requirer, requirer_cmr, provider, and provider_cmr. The
    policies can be on any combination of these relations and should produce proper
    objects.
    """
    ctx = consumer_context(policies)
    mesh_relation = scenario.Relation(endpoint="service-mesh", interface="service_mesh")
    rela = scenario.Relation("rela", "foo", remote_app_name="remote_a")
    relb = scenario.Relation("relb", "foo", remote_app_name="masked_name_b")
    cmr_relb = scenario.Relation(
        "provide-cmr-mesh",
        "cross_model_mesh",
        remote_app_name="masked_name_b",
        remote_app_data={
            "cmr_data": json.dumps(
                {
                    "app_name": "remote_b",
                    "juju_model_name": "remote_model",
                }
            )
        },
    )
    relc = scenario.Relation("relc", "foo", remote_app_name="remote_c")
    reld = scenario.Relation("reld", "foo", remote_app_name="masked_name_d")
    cmr_reld = scenario.Relation(
        "provide-cmr-mesh",
        "cross_model_mesh",
        remote_app_name="masked_name_d",
        remote_app_data={
            "cmr_data": json.dumps(
                {
                    "app_name": "remote_d",
                    "juju_model_name": "remote_model",
                }
            )
        },
    )
    state = scenario.State(
        relations={
            mesh_relation,
            rela,
            relb,
            cmr_relb,
            relc,
            reld,
            cmr_reld,
        },
        leader=True,
        model=scenario.Model(name="my_model"),
    )
    out = ctx.run(ctx.on.relation_created(relation=mesh_relation), state)
    assert (
        json.loads(out.get_relation(mesh_relation.id).local_app_data["policies"]) == expected_data
    )


def lightkube_client_mock(managed_labels: dict) -> MagicMock:
    """Return a mock lightkube client with a ConfigMap tracking the given managed labels.

    The StatefulSet and Service are no longer read by reconcile_charm_labels (it uses minimal
    patches instead), so only the ConfigMap is returned via client.get().

    Args:
        managed_labels (dict): Labels that are currently managed by reconcile_charm_labels,
                               stored in the ConfigMap.
    """
    client = MagicMock()

    # Mock ConfigMap with a labels field in data
    config_map = MagicMock()
    # ConfigMap is a memory of what labels are currently managed.
    config_map.data = {"labels": json.dumps(managed_labels)}

    client.get.return_value = config_map

    return client


def assert_charm_kubernetes_objects_have_labels(expected_patch, expected_in_configmap, mock_client: MagicMock):
    """Assert that the mock client has patched the StatefulSet, Service, and ConfigMap as expected.

    Args:
        expected_patch (dict): The labels that should be sent as a minimal patch to the StatefulSet and Service.
        expected_in_configmap (dict): The labels that should be present in the ConfigMap's data field under "labels".
        mock_client (MagicMock): The mock lightkube client that was used to patch the resources.
    """
    # Ensure the patched resources have the expected labels
    patched_statefulset = [call_args.kwargs['obj'] for call_args in mock_client.patch.call_args_list if
                           call_args.kwargs['res'] is StatefulSet]
    assert len(patched_statefulset) == 1
    assert patched_statefulset[0] == {"spec": {"template": {"metadata": {"labels": expected_patch}}}}
    patched_service = [call_args.kwargs['obj'] for call_args in mock_client.patch.call_args_list if
                       call_args.kwargs['res'] is Service]
    assert len(patched_service) == 1
    assert patched_service[0] == {"metadata": {"labels": expected_patch}}
    patched_configmap = [call_args.kwargs['obj'] for call_args in mock_client.patch.call_args_list if
                         call_args.kwargs['res'] is ConfigMap]
    assert len(patched_configmap) == 1
    assert len(patched_configmap[0].data) == 1
    assert json.loads(patched_configmap[0].data["labels"]) == expected_in_configmap


@pytest.mark.parametrize(
    "initial_managed_labels, desired_managed_labels, expected_patch",
    [
        # Add label to objects
        (
            {},
            {"key-added": "value-added"},
            {"key-added": "value-added"},
        ),
        # Add one label, update one label, and remove one label
        (
            {"key-to-be-removed": "value-to-be-removed", "key-to-be-updated": "value-to-be-updated"},
            {"key-to-be-updated": "value-updated", "key-added": "value-added"},
            {"key-to-be-removed": None, "key-to-be-updated": "value-updated", "key-added": "value-added"}
        ),
        # Remove labels
        (
            {"key-to-be-removed": "v", "key-to-be-removed2": "v"},
            {},
            {"key-to-be-removed": None, "key-to-be-removed2": None},
        ),

    ]
)
def test_reconcile_charm_labels(
        initial_managed_labels,
        desired_managed_labels,
        expected_patch
):
    """Test that reconcile_charm_labels correctly patches the StatefulSet, Service, and ConfigMap with the labels.

    Args:
        initial_managed_labels (dict): Labels on the kubernetes objects before execution
        desired_managed_labels (dict): The labels that should be present after execution.
        expected_patch (dict): The labels our client.patch() should send to Kubernetes
    """
    mock_client = lightkube_client_mock(managed_labels=initial_managed_labels)

    reconcile_charm_labels(
        client=mock_client,
        app_name="my-app",
        namespace="test-ns",
        label_configmap_name="my-cm",
        labels=desired_managed_labels.copy(),
    )

    assert_charm_kubernetes_objects_have_labels(expected_patch=expected_patch, expected_in_configmap=desired_managed_labels, mock_client=mock_client)


def test_reconcile_charm_labels_does_not_touch_unmanaged_labels():
    """Test that reconcile_charm_labels never includes unmanaged labels in its patches.

    Unmanaged labels (e.g. labels added by an admin or another controller) exist on the
    Kubernetes resources but are not tracked in the ConfigMap.  Since we use minimal strategic
    merge patches, unmanaged labels must never appear in the patch dict - their absence from the
    patch means Kubernetes leaves them untouched.
    """
    # ConfigMap only knows about managed labels, not the unmanaged ones on the actual resources
    mock_client = lightkube_client_mock(managed_labels={"managed-key": "managed-value"})

    reconcile_charm_labels(
        client=mock_client,
        app_name="my-app",
        namespace="test-ns",
        label_configmap_name="my-cm",
        labels={"managed-key": "updated-value", "new-key": "new-value"},
    )

    # Verify no unmanaged labels leaked into the patches
    expected_patch = {"managed-key": "updated-value", "new-key": "new-value"}
    for call_args in mock_client.patch.call_args_list:
        obj = call_args.kwargs["obj"]
        if isinstance(obj, dict):
            # StatefulSet or Service patch — extract the labels from the dict
            if "spec" in obj:
                patched_labels = obj["spec"]["template"]["metadata"]["labels"]
            else:
                patched_labels = obj["metadata"]["labels"]
            assert patched_labels == expected_patch, (
                f"Patch contains unexpected labels: {patched_labels}"
            )


def test_reconcile_charm_labels_configmap_created_on_404():
    """Test that reconcile_charm_labels creates its ConfigMap if it doesn't exist."""
    mocked_client = MagicMock()
    mocked_client.get.side_effect = HTTPStatusError(
        "Not found", request=Request("GET", "url"), response=Response(404)
    )

    # mock _init_label_configmap to return a mock ConfigMap with a data field that has no labels included, just so
    # reconcile_charm_labels doesn't fail
    with patch("canonical_service_mesh.utils.istio._labels._init_label_configmap") as mock_init:
        mock_init.return_value = MagicMock()
        mock_init.return_value.data = {"labels": "{}"}
        reconcile_charm_labels(
            client=mocked_client,
            app_name="my-app",
            namespace="test-ns",
            label_configmap_name="my-cm",
            labels={},
        )
        # Ensure the ConfigMap was created
        mock_init.assert_called_once()


# No need to actually reconcile anything in this test.
@patch("charmlibs.interfaces.service_mesh._service_mesh.reconcile_charm_labels")
def test_getting_relation_data(patched_reconcile: MagicMock):
    """Test that the consumer can read relation data set by a provider."""
    ctx = consumer_context([AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)])
    labels_actual = {"label1": "value1", "label2": "value2"}
    mesh_type_actual = MeshType.istio
    expected_data = ServiceMeshProviderAppData(
        labels=labels_actual,
        mesh_type=mesh_type_actual,
    )
    mesh_relation = scenario.Relation(
        endpoint="service-mesh",
        interface="service_mesh",
        remote_app_data={
            "labels": json.dumps(labels_actual),
            "mesh_type": json.dumps(mesh_type_actual)
        }
    )
    state = scenario.State(
        relations={
            mesh_relation,
        },
        leader=True,
    )
    with ctx(
        ctx.on.relation_changed(relation=mesh_relation),
        state,
    ) as manager:
        assert labels_actual == manager.charm.mesh.labels()
        assert mesh_type_actual == manager.charm.mesh.mesh_type()
        assert expected_data == manager.charm.mesh._get_app_data()
        assert manager.charm.mesh.enabled is True


@patch("charmlibs.interfaces.service_mesh._service_mesh.reconcile_charm_labels")
def test_enabled_true_when_relation_exists(patched_reconcile: MagicMock):
    """Test that enabled returns True when the mesh relation exists, even without data."""
    ctx = consumer_context([AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)])
    mesh_relation = scenario.Relation(
        endpoint="service-mesh",
        interface="service_mesh",
    )
    state = scenario.State(
        relations={
            mesh_relation,
        },
        leader=True,
    )
    with ctx(
        ctx.on.relation_changed(relation=mesh_relation),
        state,
    ) as manager:
        assert manager.charm.mesh.enabled is True


def test_enabled_false_when_no_relation():
    """Test that enabled returns False when there is no mesh relation."""
    ctx = consumer_context([AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)])
    state = scenario.State(
        relations=set(),
        leader=True,
    )
    with ctx(
        ctx.on.start(),
        state,
    ) as manager:
        assert manager.charm.mesh.enabled is False


@patch("charmlibs.interfaces.service_mesh._service_mesh.reconcile_charm_labels")
def test_enabled_false_after_relation_broken(patched_reconcile: MagicMock):
    """Test that enabled returns False after the mesh relation is broken."""
    ctx = consumer_context([AppPolicy(relation="rela", endpoints=[ENDPOINT_A], service=None)])
    mesh_relation = scenario.Relation(
        endpoint="service-mesh",
        interface="service_mesh",
    )
    state = scenario.State(
        relations={
            mesh_relation,
        },
        leader=True,
    )
    with ctx(
        ctx.on.relation_broken(relation=mesh_relation),
        state,
    ) as manager:
        assert manager.charm.mesh.enabled is False
