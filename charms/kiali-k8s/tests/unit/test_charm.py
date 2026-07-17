#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from contextlib import nullcontext as does_not_raise
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from observability_charm_tools.exceptions import BlockedStatusError, WaitingStatusError
from ops import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import Layer
from scenario import Container, Relation, State

from charm import KialiCharm, TempoConfigurationData

REMOTE_PROMETHEUS_MODEL = "some-model"
REMOTE_PROMETHEUS_MODEL_UUID = "1"
REMOTE_PROMETHEUS_TYPE = "prometheus"
REMOTE_PROMETHEUS_URL = "http://prometheus:9090/"
REMOTE_ISTIO_APP_NAME = "istio"
REMOTE_ISTIO_NAMESPACE = "istio-model"
GRAFANA_INTERNAL_URL = "http://grafana:3000/"
GRAFANA_EXTERNAL_URL = "http://grafana.example.com/"
GRAFANA_UID = "grafana-uid"
TEMPO_CONFIGURATION = TempoConfigurationData(
    datasource_uid="tempo-datasource-uid",
    internal_url="http://tempo:16686",
    external_url="http://tempo.example.com",
)
REMOTE_TEMPO_URL = "http://tempo:16686"


def mock_grafana_relation(
    internal_url=GRAFANA_INTERNAL_URL, external_url=GRAFANA_EXTERNAL_URL
) -> Relation:
    """Return a mock relation to grafana."""
    return Relation(
        endpoint="grafana-metadata",
        interface="grafana_metadata",
        remote_app_name="grafana",
        remote_app_data={
            "direct_url": internal_url,
            "ingress_url": external_url,
            "grafana_uid": GRAFANA_UID,
        },
    )


def mock_prometheus_relation(direct_url=REMOTE_PROMETHEUS_URL) -> Relation:
    """Return a mock relation to prometheus."""
    return Relation(
        endpoint="prometheus-api",
        interface="prometheus_api",
        remote_app_name="prometheus",
        remote_app_data={
            "direct_url": direct_url,
        },
    )


def mock_istio_metadata_relation(root_namespace=REMOTE_ISTIO_NAMESPACE) -> Relation:
    """Return a mock relation for istio-metadata."""
    return Relation(
        endpoint="istio-metadata",
        interface="istio_metadata",
        remote_app_name="istio",
        remote_app_data={
            "root_namespace": root_namespace,
        },
    )


def mock_tempo_api_relation(direct_url=REMOTE_TEMPO_URL) -> Relation:
    """Return a mock relation for tempo-api."""
    return Relation(
        endpoint="tempo-api",
        interface="tempo-api",
        remote_app_name="tempo",
        remote_app_data={
            "http": json.dumps({"direct_url": direct_url}),
            # Required, but not used in this test
            "grpc": json.dumps({"direct_url": "http://unused.com"}),
        },
    )


def mock_tempo_datasource_exchange() -> Relation:
    """Return a mock relation for tempo-datasource-exchange."""
    return Relation(
        endpoint="tempo-datasource-exchange",
        interface="grafana-datasource-exchange",
        remote_app_name="tempo",
        remote_app_data={
            "datasources": json.dumps(
                [{"type": "tempo", "uid": "tempo-datasource-uid", "grafana_uid": GRAFANA_UID}]
            )
        },
    )


def mock_is_kiali_available(raises: Optional[Exception]):
    """Return a mock for is_kiali_available that, when called, will either raise or return True."""

    def f(*args, **kwargs):
        if raises:
            raise raises
        return True

    return f


@pytest.mark.parametrize(
    "container, relations, kiali_available_mock, expected_status",
    [
        (
            # Has prometheus and istio-metadata - Active
            Container(name="kiali", can_connect=True),
            [
                mock_prometheus_relation(),
                mock_istio_metadata_relation(),
            ],
            mock_is_kiali_available(raises=None),
            ActiveStatus,
        ),
        (
            # Inactive - container not ready
            Container(name="kiali", can_connect=False),
            [
                mock_prometheus_relation(),
                mock_istio_metadata_relation(),
            ],
            mock_is_kiali_available(raises=WaitingStatusError("")),
            WaitingStatus,
        ),
        (
            # Inactive - prometheus relation not ready
            Container(
                name="kiali",
                can_connect=True,
                layers={"kiali": Layer({"services": {"kiali": {"summary": "kiali"}}})},
            ),
            [
                mock_istio_metadata_relation(),
            ],
            mock_is_kiali_available(raises=WaitingStatusError("")),
            BlockedStatus,
        ),
        (
            # Inactive - istio-metadata relation not ready
            Container(
                name="kiali",
                can_connect=True,
                layers={"kiali": Layer({"services": {"kiali": {"summary": "kiali"}}})},
            ),
            [
                mock_istio_metadata_relation(),
            ],
            mock_is_kiali_available(raises=WaitingStatusError("")),
            BlockedStatus,
        ),
        (
            # Inactive - inputs ready, but kiali not available
            Container(name="kiali", can_connect=True),
            [
                mock_prometheus_relation(),
                mock_istio_metadata_relation(),
            ],
            mock_is_kiali_available(raises=WaitingStatusError("")),
            WaitingStatus,
        ),
    ],
)
def test_charm_given_inputs(
    this_charm_context, container, relations, kiali_available_mock, expected_status
):
    """Tests that the charm responds as expected to standard inputs."""
    # Arrange
    state = State(
        containers=[container],
        relations=relations,
        leader=True,
    )

    with patch("charm._is_kiali_available", kiali_available_mock):
        out = this_charm_context.run(this_charm_context.on.config_changed(), state)

    assert isinstance(out.unit_status, expected_status)


@pytest.mark.parametrize(
    "prometheus_url, istio_namespace, grafana_internal_url, grafana_external_url, tempo_configuration, expected, expected_context",
    [
        (
            # Active: All inputs provided.
            REMOTE_PROMETHEUS_URL,
            REMOTE_ISTIO_NAMESPACE,
            # Include a trailing slash here to ensure we remove them during parsing.  Kiali doesn't accept trailing
            # slashes
            GRAFANA_INTERNAL_URL,
            GRAFANA_EXTERNAL_URL,
            TEMPO_CONFIGURATION,
            {
                "auth": {"strategy": "anonymous"},
                "deployment": {"view_only_mode": True},
                "external_services": {
                    "prometheus": {"url": REMOTE_PROMETHEUS_URL},
                    "grafana": {
                        "enabled": True,
                        "internal_url": GRAFANA_INTERNAL_URL.rstrip("/"),
                        "external_url": GRAFANA_EXTERNAL_URL.rstrip("/"),
                    },
                    "tracing": {
                        "enabled": True,
                        "internal_url": TEMPO_CONFIGURATION["internal_url"],
                        "external_url": TEMPO_CONFIGURATION["external_url"],
                        "provider": "tempo",
                        "tempo_config": {
                            "org_id": "1",
                            "datasource_uid": TEMPO_CONFIGURATION["datasource_uid"],
                            "url_format": "grafana",
                        },
                        "use_grpc": False,
                    },
                },
                "istio_namespace": REMOTE_ISTIO_NAMESPACE,
                "server": {"port": 20001, "web_root": "/"},
            },
            does_not_raise(),
        ),
        (
            # Active: All inputs except optional grafana and tempo provided.
            REMOTE_PROMETHEUS_URL,
            REMOTE_ISTIO_NAMESPACE,
            None,
            None,
            None,
            {
                "auth": {"strategy": "anonymous"},
                "deployment": {"view_only_mode": True},
                "external_services": {
                    "prometheus": {"url": REMOTE_PROMETHEUS_URL},
                },
                "istio_namespace": REMOTE_ISTIO_NAMESPACE,
                "server": {"port": 20001, "web_root": "/"},
            },
            does_not_raise(),
        ),
        (
            # Inactive: Missing Prometheus data should raise an exception.
            None,
            "istio-namespace",
            None,
            None,
            None,
            None,
            pytest.raises(BlockedStatusError),
        ),
        (
            # Inactive: Missing istio namespace should raise an exception.
            "http://prometheus:9090",
            None,
            None,
            None,
            None,
            None,
            pytest.raises(BlockedStatusError),
        ),
    ],
    # TODO: case with tracing
)
def test_kiali_config(
    this_charm,
    this_charm_context,
    prometheus_url,
    istio_namespace,
    grafana_internal_url,
    grafana_external_url,
    tempo_configuration,
    expected,
    expected_context,
):
    """Test that the generated kiali configuration matches the expected output or raises the expected exception."""
    with this_charm_context(this_charm_context.on.update_status(), state=State()) as manager:
        charm: this_charm = manager.charm
        # Default value in case we raise an exception
        with expected_context:
            kiali_config = charm._generate_kiali_config(
                prometheus_url=prometheus_url,
                istio_namespace=istio_namespace,
                grafana_internal_url=grafana_internal_url,
                grafana_external_url=grafana_external_url,
                tempo_configuration=tempo_configuration,
            )
            # If above doesn't raise, compare output
            assert kiali_config == expected


@pytest.mark.parametrize(
    "prometheus_relation, istio_metadata_relation, grafana_metadata_relation, tempo_api_relation, tempo_datasource_exchange_relation",
    [
        # Prometheus and istio-metadata relations only
        (
            mock_prometheus_relation(direct_url=REMOTE_PROMETHEUS_URL),
            mock_istio_metadata_relation(root_namespace=REMOTE_ISTIO_NAMESPACE),
            None,
            None,
            None,
        ),
        # Prometheus, istio-metadata, and grafana relations
        (
            mock_prometheus_relation(direct_url=REMOTE_PROMETHEUS_URL),
            mock_istio_metadata_relation(root_namespace=REMOTE_ISTIO_NAMESPACE),
            mock_grafana_relation(
                internal_url=GRAFANA_INTERNAL_URL, external_url=GRAFANA_EXTERNAL_URL
            ),
            None,
            None,
        ),
        # Prometheus, istio-metadata, grafana relations, and both tempo relations
        (
            mock_prometheus_relation(direct_url=REMOTE_PROMETHEUS_URL),
            mock_istio_metadata_relation(root_namespace=REMOTE_ISTIO_NAMESPACE),
            mock_grafana_relation(
                internal_url=GRAFANA_INTERNAL_URL, external_url=GRAFANA_EXTERNAL_URL
            ),
            mock_tempo_api_relation(direct_url=REMOTE_TEMPO_URL),
            mock_tempo_datasource_exchange(),
        ),
    ],
)
def test_e2e_charm_configuration(
    this_charm_context,
    prometheus_relation,
    istio_metadata_relation,
    grafana_metadata_relation,
    tempo_api_relation,
    tempo_datasource_exchange_relation,
):
    """An end-to-end spot test confirming configuration is correctly passed from relations to _generate_kiali_config.

    This test is meant to confirm relation data that contributes to Kiali's configuration is correctly reaching the
    _generate_kaili_config method.
    """
    # Arrange
    relations = []
    prometheus_url_expected = None
    istio_namespace_expected = None
    grafana_internal_url_expected = None
    grafana_external_url_expected = None
    tempo_configuration = None

    if prometheus_relation:
        relations.append(prometheus_relation)
        prometheus_url_expected = prometheus_relation.remote_app_data["direct_url"]
    if istio_metadata_relation:
        relations.append(istio_metadata_relation)
        istio_namespace_expected = istio_metadata_relation.remote_app_data["root_namespace"]
    if grafana_metadata_relation:
        relations.append(grafana_metadata_relation)
        # remove the trailing slash, as we intentionally strip it out to keep Kiali happy
        grafana_internal_url_expected = str(
            grafana_metadata_relation.remote_app_data["direct_url"]
        )
        grafana_external_url_expected = str(
            grafana_metadata_relation.remote_app_data["ingress_url"]
        )
    if tempo_api_relation and tempo_datasource_exchange_relation:
        relations.append(tempo_api_relation)
        relations.append(tempo_datasource_exchange_relation)
        internal_url = json.loads(tempo_api_relation.remote_app_data["http"])["direct_url"]
        external_url = (
            json.loads(tempo_api_relation.remote_app_data["http"]).get("ingress_url", None)
            or internal_url
        )
        tempo_configuration = TempoConfigurationData(
            internal_url=internal_url,
            external_url=external_url,
            datasource_uid=json.loads(
                tempo_datasource_exchange_relation.remote_app_data["datasources"]
            )[0]["uid"],
        )

    state = State(
        containers=[
            Container(name="kiali", can_connect=True),
        ],
        relations=relations,
        leader=True,
    )

    # Act
    with this_charm_context(this_charm_context.on.config_changed(), state) as manager:
        charm: KialiCharm = manager.charm
        mock_generate_kiali_config = MagicMock()
        charm._generate_kiali_config = mock_generate_kiali_config
        # We don't need to actually configure anything
        charm._configure_kiali_workload = MagicMock()
        manager.run()

        # Assert
        mock_generate_kiali_config.assert_called_once_with(
            prometheus_url=prometheus_url_expected,
            istio_namespace=istio_namespace_expected,
            grafana_internal_url=grafana_internal_url_expected,
            grafana_external_url=grafana_external_url_expected,
            tempo_configuration=tempo_configuration,
        )
