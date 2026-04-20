# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from canonical_service_mesh.utils import (
    get_peer_identity_for_juju_application,
    get_peer_identity_for_service_account,
)


def test_peer_identity_for_service_account():
    result = get_peer_identity_for_service_account("mysa", "mynamespace")
    assert result == "cluster.local/ns/mynamespace/sa/mysa"


def test_peer_identity_for_juju_application():
    result = get_peer_identity_for_juju_application("myapp", "mymodel")
    assert result == "cluster.local/ns/mymodel/sa/myapp"
