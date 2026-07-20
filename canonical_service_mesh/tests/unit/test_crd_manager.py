# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock

import pytest
from lightkube.models.apiextensions_v1 import (
    CustomResourceDefinitionCondition,
    CustomResourceDefinitionNames,
    CustomResourceDefinitionSpec,
    CustomResourceDefinitionStatus,
)
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition

from canonical_service_mesh.k8s.resource_manager import (
    CustomResourceDefinitionManager,
    FakeApiError,
)

_SPEC = CustomResourceDefinitionSpec(
    group="example.com",
    names=CustomResourceDefinitionNames(kind="Widget", plural="widgets"),
    scope="Cluster",
    versions=[],
)


def _crd(name):
    return CustomResourceDefinition(metadata=ObjectMeta(name=name), spec=_SPEC)


def _live_crd(name, conditions):
    status = (
        CustomResourceDefinitionStatus(conditions=conditions) if conditions is not None else None
    )
    return CustomResourceDefinition(metadata=ObjectMeta(name=name), spec=_SPEC, status=status)


def _condition(type_, status):
    return CustomResourceDefinitionCondition(type=type_, status=status)


def _manager(client):
    charm = MagicMock()
    charm.app.name = "app"
    charm.model.name = "model"
    return CustomResourceDefinitionManager(charm, client, scope="crds")


@pytest.mark.parametrize(
    "conditions, expected",
    [
        ([_condition("Established", "True")], True),
        ([_condition("NamesAccepted", "True"), _condition("Established", "True")], True),
        ([_condition("Established", "False")], False),
        ([_condition("NamesAccepted", "True")], False),
        ([], False),
        (None, False),
    ],
)
def test_established_reads_condition(conditions, expected):
    client = MagicMock()
    client.get.return_value = _live_crd("widgets.example.com", conditions)
    manager = _manager(client)

    assert manager.established([_crd("widgets.example.com")]) is expected


def test_established_requires_every_crd():
    established = _live_crd("a.example.com", [_condition("Established", "True")])
    pending = _live_crd("b.example.com", [_condition("Established", "False")])
    client = MagicMock()
    client.get.side_effect = [established, pending]
    manager = _manager(client)

    assert manager.established([_crd("a.example.com"), _crd("b.example.com")]) is False


@pytest.mark.parametrize("code", [404, 429], ids=["not-present", "initialising"])
def test_established_treats_api_error_as_not_established(code):
    client = MagicMock()
    client.get.side_effect = FakeApiError(code)
    manager = _manager(client)

    assert manager.established([_crd("widgets.example.com")]) is False


def test_reconcile_delegates_to_krm():
    manager = _manager(MagicMock())
    manager._krm = MagicMock()
    resources = [_crd("widgets.example.com")]

    manager.reconcile(resources)

    manager._krm.reconcile.assert_called_once_with(resources)
