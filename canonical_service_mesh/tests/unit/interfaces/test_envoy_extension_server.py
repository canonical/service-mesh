# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the envoy-extension-server interface library."""

from __future__ import annotations

import json

import ops
import pytest
from ops.charm import CharmBase
from ops.testing import Context, Relation, State

from canonical_service_mesh.interfaces.envoy_extension_server import (
    ExtensionServerData,
    ExtensionServerProvider,
    ExtensionServerRequirer,
)

PROVIDER_META = {
    "name": "provider-charm",
    "provides": {"envoy-extension-server": {"interface": "envoy_extension_server"}},
}

REQUIRER_META = {
    "name": "requirer-charm",
    "requires": {"envoy-extension-server": {"interface": "envoy_extension_server"}},
}


class ProviderCharm(CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.ext_server = ExtensionServerProvider(self)
        self.framework.observe(
            self.on["envoy-extension-server"].relation_changed, self._on_changed
        )

    def _on_changed(self, _: ops.EventBase) -> None:
        self.ext_server.publish_data(
            extension_server_fqdn="ai.my-model.svc.cluster.local",
        )


class RequirerCharm(CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.ext_server = ExtensionServerRequirer(self)
        self.framework.observe(
            self.on["envoy-extension-server"].relation_changed, self._on_changed
        )

    def _on_changed(self, _: ops.EventBase) -> None:
        self.ext_server.publish_controller_identity(
            controller_name="envoy-controller-k8s",
            namespace="my-model",
        )


def _provider_databag(fqdn: str = "ai.my-model.svc.cluster.local", port: str = "1063"):
    return {
        "extension_server_fqdn": json.dumps(fqdn),
        "extension_server_port": json.dumps(port),
    }


def test_provider_publishes_extension_server_address():
    relation = Relation(endpoint="envoy-extension-server", interface="envoy_extension_server")
    ctx = Context(ProviderCharm, meta=PROVIDER_META)
    state_out = ctx.run(
        ctx.on.relation_changed(relation=relation),
        State(relations=[relation], leader=True),
    )
    rel_out = state_out.get_relation(relation.id)
    assert json.loads(rel_out.local_app_data["extension_server_fqdn"]) == (
        "ai.my-model.svc.cluster.local"
    )
    assert json.loads(rel_out.local_app_data["extension_server_port"]) == "1063"


def test_provider_skips_publish_when_not_leader():
    relation = Relation(endpoint="envoy-extension-server", interface="envoy_extension_server")
    ctx = Context(ProviderCharm, meta=PROVIDER_META)
    state_out = ctx.run(
        ctx.on.relation_changed(relation=relation),
        State(relations=[relation], leader=False),
    )
    rel_out = state_out.get_relation(relation.id)
    assert "extension_server_fqdn" not in rel_out.local_app_data


def test_requirer_publishes_controller_identity():
    relation = Relation(endpoint="envoy-extension-server", interface="envoy_extension_server")
    ctx = Context(RequirerCharm, meta=REQUIRER_META)
    state_out = ctx.run(
        ctx.on.relation_changed(relation=relation),
        State(relations=[relation], leader=True),
    )
    rel_out = state_out.get_relation(relation.id)
    assert json.loads(rel_out.local_app_data["controller_name"]) == "envoy-controller-k8s"
    assert json.loads(rel_out.local_app_data["namespace"]) == "my-model"


def test_requirer_reads_provider_address():
    relation = Relation(
        endpoint="envoy-extension-server",
        interface="envoy_extension_server",
        remote_app_name="ai-charm",
        remote_app_data=_provider_databag(),
    )
    ctx = Context(RequirerCharm, meta=REQUIRER_META)
    with ctx(
        ctx.on.relation_changed(relation=relation),
        State(relations=[relation], leader=True),
    ) as mgr:
        data = mgr.charm.ext_server.get_extension_server_data()
        assert data is not None
        assert data.extension_server_fqdn == "ai.my-model.svc.cluster.local"
        assert data.extension_server_port == "1063"
        assert mgr.charm.ext_server.is_ready is True


def test_requirer_not_ready_without_relation():
    ctx = Context(RequirerCharm, meta=REQUIRER_META)
    with ctx(ctx.on.start(), State(leader=True)) as mgr:
        assert mgr.charm.ext_server.is_ready is False
        assert mgr.charm.ext_server.get_extension_server_data() is None


def test_requirer_not_ready_with_partial_provider_data():
    relation = Relation(
        endpoint="envoy-extension-server",
        interface="envoy_extension_server",
        remote_app_name="ai-charm",
        remote_app_data={"extension_server_fqdn": json.dumps("ai.my-model.svc.cluster.local")},
    )
    ctx = Context(RequirerCharm, meta=REQUIRER_META)
    with ctx(
        ctx.on.relation_changed(relation=relation),
        State(relations=[relation], leader=True),
    ) as mgr:
        assert mgr.charm.ext_server.is_ready is False


def test_provider_reads_controller_identity():
    relation = Relation(
        endpoint="envoy-extension-server",
        interface="envoy_extension_server",
        remote_app_name="eg-charm",
        remote_app_data={
            "controller_name": json.dumps("envoy-controller-k8s"),
            "namespace": json.dumps("my-model"),
        },
    )
    ctx = Context(ProviderCharm, meta=PROVIDER_META)
    with ctx(
        ctx.on.relation_changed(relation=relation),
        State(relations=[relation], leader=True),
    ) as mgr:
        identity = mgr.charm.ext_server.get_controller_identity()
        assert identity is not None
        assert identity.controller_name == "envoy-controller-k8s"
        assert identity.namespace == "my-model"


def test_port_validation_rejects_non_integer():
    with pytest.raises(ValueError, match="convertible to an integer"):
        ExtensionServerData(extension_server_port="not-a-number")
