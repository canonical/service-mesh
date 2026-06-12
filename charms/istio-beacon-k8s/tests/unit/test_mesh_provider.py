import json

import pytest
import scenario
from charmlibs.interfaces.service_mesh import (
    MeshPolicy,
    MeshType,
    PolicyTargetType,
    ServiceMeshProvider,
    ServiceMeshProviderAppData,
)
from ops import CharmBase

MESH_LABELS = {
    "label1": "value1",
    "label2": "value2",
}
MESH_RELATION_NAME = "service-mesh-relation"
MESH_INTERFACE_NAME = "service_mesh_interface"
MESH_TYPE = MeshType.istio


def provider_context() -> scenario.Context:
    meta = {
        "name": "provider-charm",
        "provides": {
            MESH_RELATION_NAME: {"interface": MESH_INTERFACE_NAME},
        },
    }


    class Charm(CharmBase):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.mesh = ServiceMeshProvider(
                self,
                labels=MESH_LABELS,
                mesh_relation_name=MESH_RELATION_NAME,
                mesh_type=MESH_TYPE
            )

    return scenario.Context(Charm, meta)


def test_provider_sends_data():
    ctx = provider_context()
    mesh_relation = scenario.Relation(
        endpoint=MESH_RELATION_NAME,
        interface=MESH_INTERFACE_NAME,
    )
    state = scenario.State(
        relations=[mesh_relation],
        leader=True,
    )
    out = ctx.run(ctx.on.relation_created(mesh_relation), state)
    raw_data = {k: json.loads(v) for k, v in out.get_relation(mesh_relation.id).local_app_data.items()}
    actual = ServiceMeshProviderAppData.model_validate(raw_data)
    assert actual.labels == MESH_LABELS
    assert actual.mesh_type == MESH_TYPE


EXAMPLE_MESH_POLICY_1 = MeshPolicy(
    source_namespace="namespace1-1",
    source_app_name="app1-1",
    target_namespace="namespace2-1",
    target_app_name="app2-1",
    target_type=PolicyTargetType.app,
    endpoints=[],
)

EXAMPLE_MESH_POLICY_2 = MeshPolicy(
    source_namespace="namespace1-2",
    source_app_name="app-2",
    target_namespace="namespace-2",
    target_app_name="app-2",
    target_type=PolicyTargetType.app,
    endpoints=[],
)

EXAMPLE_MESH_POLICY_3 = MeshPolicy(
    source_namespace="namespace1-3",
    source_app_name="app1-3",
    target_namespace="namespace2-3",
    target_app_name="app2-3",
    target_type=PolicyTargetType.app,
    endpoints=[],
)

@pytest.mark.parametrize(
    "mesh_relations, expected_data",
    [
        # Two relations, both with policies
        (
            [
                scenario.Relation(
                    endpoint=MESH_RELATION_NAME,
                    interface=MESH_INTERFACE_NAME,
                    remote_app_data={
                        "policies": json.dumps([
                            EXAMPLE_MESH_POLICY_1.model_dump(mode="json"),
                            EXAMPLE_MESH_POLICY_2.model_dump(mode="json"),
                        ]),
                    },
                ),
                scenario.Relation(
                    endpoint=MESH_RELATION_NAME,
                    interface=MESH_INTERFACE_NAME,
                    remote_app_data={
                        "policies": json.dumps([
                            EXAMPLE_MESH_POLICY_3.model_dump(mode="json"),
                        ]),
                    },
                ),
            ],

            [EXAMPLE_MESH_POLICY_1, EXAMPLE_MESH_POLICY_2, EXAMPLE_MESH_POLICY_3],
        ),
        # Two relations, second has no policies
        (
            [
                scenario.Relation(
                    endpoint=MESH_RELATION_NAME,
                    interface=MESH_INTERFACE_NAME,
                    remote_app_data={
                        "policies": json.dumps([
                            EXAMPLE_MESH_POLICY_1.model_dump(mode="json"),
                            EXAMPLE_MESH_POLICY_2.model_dump(mode="json"),
                        ]),
                    },
                ),
                scenario.Relation(
                    endpoint=MESH_RELATION_NAME,
                    interface=MESH_INTERFACE_NAME,
                    remote_app_data={
                        "policies": json.dumps([]),
                    },
                ),
            ],

            [EXAMPLE_MESH_POLICY_1, EXAMPLE_MESH_POLICY_2],
        ),
        # Two relations, second has an empty relation (other side hasn't responded yet)
        (
            [
                scenario.Relation(
                    endpoint=MESH_RELATION_NAME,
                    interface=MESH_INTERFACE_NAME,
                    remote_app_data={
                        "policies": json.dumps([
                            EXAMPLE_MESH_POLICY_1.model_dump(mode="json"),
                            EXAMPLE_MESH_POLICY_2.model_dump(mode="json"),
                        ]),
                    },
                ),
                scenario.Relation(
                    endpoint=MESH_RELATION_NAME,
                    interface=MESH_INTERFACE_NAME,
                    remote_app_data={},
                ),
            ],

            [EXAMPLE_MESH_POLICY_1, EXAMPLE_MESH_POLICY_2],
        ),
    ]
)
def test_provider_reads_data(mesh_relations, expected_data):
    ctx = provider_context()
    state = scenario.State(
        relations=mesh_relations,
    )
    with ctx(
        ctx.on.update_status(),  # any non-consequential event, just to get a charm object to play with
        state=state,
    ) as manager:
        actual_mesh_policies = manager.charm.mesh.mesh_info()

        assert actual_mesh_policies == expected_data
