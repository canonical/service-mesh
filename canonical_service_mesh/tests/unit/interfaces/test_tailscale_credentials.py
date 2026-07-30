# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from canonical_service_mesh.interfaces.tailscale_credentials import (
    ProviderAppData,
    TailscaleCredentials,
    TailscaleCredentialsProvider,
    TailscaleCredentialsRequirer,
)


@pytest.fixture()
def mock_app():
    app = MagicMock()
    app.name = "test-app"
    return app


@pytest.fixture()
def mock_relation(mock_app):
    relation = MagicMock()
    relation.app = MagicMock()
    relation.app.name = "remote-app"
    relation.data = {mock_app: {}, relation.app: {}}
    return relation


@pytest.fixture()
def mock_relation_mapping(mock_relation):
    return {
        "tailscale-credentials": [mock_relation],
        "some-other-relation": [...],
    }


def test_provider_publish(mock_relation_mapping, mock_app, mock_relation):
    """Provider publishes non-secret app data to the relation databag."""
    provider = TailscaleCredentialsProvider(mock_relation_mapping, mock_app)
    provider.publish(
        mock_relation,
        ProviderAppData(
            secret_id="secret://abc",
            login_server="https://controlplane.example.com",
            tags=["tag:a", "tag:b"],
        ),
    )

    databag = mock_relation.data[mock_app]
    assert databag["secret_id"] == "secret://abc"
    assert databag["login_server"] == "https://controlplane.example.com"


def test_provider_publish_tags_comma_roundtrip(mock_relation_mapping, mock_app, mock_relation):
    """Tags are wire-encoded and round-trip back through the requirer."""
    provider = TailscaleCredentialsProvider(mock_relation_mapping, mock_app)
    provider.publish(
        mock_relation,
        ProviderAppData(
            secret_id="secret://abc",
            login_server="https://cp.example.com",
            tags=["tag:a", "tag:b"],
        ),
    )

    databag = mock_relation.data[mock_app]
    assert databag["tags"] == "tag:a,tag:b"

    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    mock_relation.data[mock_relation.app] = databag
    provider_data = requirer.get_provider_data(mock_relation)
    assert provider_data is not None
    assert provider_data.tags == ["tag:a", "tag:b"]


def test_provider_app_data_rejects_empty_login_server():
    """ProviderAppData rejects an empty login_server."""
    with pytest.raises(ValueError, match="login_server must be non-empty"):
        ProviderAppData(secret_id="secret://abc", login_server="")


def test_secret_content_roundtrip():
    """to_secret_content serializes and model_validate parses it back cleanly."""
    content = TailscaleCredentials(
        auth_key="tskey-client-xyz", client_id="key-id-123"
    ).to_secret_content()
    assert content == {"auth-key": "tskey-client-xyz", "client-id": "key-id-123"}

    credentials = TailscaleCredentials.model_validate(content)
    assert credentials.auth_key == "tskey-client-xyz"
    assert credentials.client_id == "key-id-123"


def test_requirer_get_provider_data(mock_relation_mapping, mock_app, mock_relation):
    """Requirer reads and validates the provider's non-secret app data."""
    mock_relation.data[mock_relation.app] = {
        "secret_id": "secret://abc",
        "login_server": "https://cp.example.com",
        "tags": "tag:a",
    }
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    data = requirer.get_provider_data(mock_relation)

    assert data is not None
    assert data.secret_id == "secret://abc"
    assert data.login_server == "https://cp.example.com"
    assert data.tags == ["tag:a"]


def test_requirer_get_provider_data_empty_returns_none(
    mock_relation_mapping, mock_app, mock_relation
):
    """Requirer returns None when the provider databag is empty."""
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.get_provider_data(mock_relation) is None


def test_requirer_get_provider_data_invalid_returns_none(
    mock_relation_mapping, mock_app, mock_relation
):
    """Requirer returns None when the provider databag fails validation."""
    mock_relation.data[mock_relation.app] = {
        "secret_id": "secret://abc",
        "login_server": "",
    }
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.get_provider_data(mock_relation) is None


def test_requirer_is_ready_true(mock_relation_mapping, mock_app, mock_relation):
    """is_ready is True when provider data with a secret_id is present."""
    mock_relation.data[mock_relation.app] = {
        "secret_id": "secret://abc",
        "login_server": "https://cp.example.com",
    }
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.is_ready(mock_relation) is True


def test_requirer_is_ready_false_without_secret_id(mock_relation_mapping, mock_app, mock_relation):
    """is_ready is False when the secret_id is missing."""
    mock_relation.data[mock_relation.app] = {"login_server": "https://cp.example.com"}
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.is_ready(mock_relation) is False


def test_requirer_is_ready_false_without_login_server(
    mock_relation_mapping, mock_app, mock_relation
):
    """is_ready is False when secret_id is present but login_server is missing."""
    mock_relation.data[mock_relation.app] = {"secret_id": "secret://abc"}
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.get_provider_data(mock_relation) is not None
    assert requirer.is_ready(mock_relation) is False


def test_requirer_is_ready_false_no_provider_data(mock_relation_mapping, mock_app, mock_relation):
    """is_ready is False when there is no provider data at all."""
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.is_ready(mock_relation) is False


def test_provider_app_data_is_ready_for_use():
    """is_ready_for_use requires both secret_id and login_server."""
    assert ProviderAppData(
        secret_id="secret://abc", login_server="https://cp.example.com"
    ).is_ready_for_use()
    assert not ProviderAppData(secret_id="secret://abc").is_ready_for_use()
    assert not ProviderAppData(login_server="https://cp.example.com").is_ready_for_use()
    assert not ProviderAppData().is_ready_for_use()


def test_provider_relations(mock_relation_mapping, mock_app, mock_relation):
    """Provider relations property returns only the matching relation instances."""
    provider = TailscaleCredentialsProvider(mock_relation_mapping, mock_app)
    assert provider.relations == [mock_relation]


def test_provider_no_relations(mock_app):
    """Provider relations property is empty when no relations exist."""
    provider = TailscaleCredentialsProvider({}, mock_app)
    assert provider.relations == []


def test_requirer_relations(mock_relation_mapping, mock_app, mock_relation):
    """Requirer relations property returns the relation instances."""
    requirer = TailscaleCredentialsRequirer(mock_relation_mapping, mock_app)
    assert requirer.relations == [mock_relation]


def test_requirer_no_relations(mock_app):
    """Requirer relations property is empty when no relations exist."""
    requirer = TailscaleCredentialsRequirer({}, mock_app)
    assert requirer.relations == []


def test_provider_app_data_defaults():
    """ProviderAppData fields default to None."""
    data = ProviderAppData()
    assert data.secret_id is None
    assert data.login_server is None
    assert data.tags is None


def test_provider_app_data_encode_tags_none():
    """Serializing with tags=None yields None for the tags field."""
    dumped = ProviderAppData(secret_id="secret://abc", tags=None).model_dump(
        mode="json", by_alias=True
    )
    assert dumped["tags"] is None


def test_provider_app_data_tags_decode_from_string():
    """Tags decode from a comma-separated wire string, dropping empty entries."""
    assert ProviderAppData.model_validate({"tags": "tag:a,tag:b"}).tags == ["tag:a", "tag:b"]
    assert ProviderAppData.model_validate({"tags": ""}).tags == []
    assert ProviderAppData.model_validate({"tags": " tag:a , tag:b , "}).tags == [
        "tag:a",
        "tag:b",
    ]


def test_tailscale_credentials_alias_construction():
    """TailscaleCredentials constructs from dash-cased aliases."""
    creds = TailscaleCredentials.model_validate(
        {"auth-key": "tskey-client-1", "client-id": "id-1"}
    )
    assert creds.auth_key == "tskey-client-1"
    assert creds.client_id == "id-1"
