#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for managing Kiali."""

import logging
from pathlib import Path
from typing import Optional, TypedDict
from urllib.parse import urlparse

import ops
import requests
import yaml
from charms.grafana_k8s.v0.grafana_metadata import GrafanaMetadataAppData, GrafanaMetadataRequirer
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshConsumer, UnitPolicy
from charms.istio_k8s.v0.istio_metadata import IstioMetadataRequirer
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.mimir_coordinator_k8s.v0.prometheus_api import PrometheusApiRequirer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.tempo_api import TempoApiAppData, TempoApiRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from cosl.interfaces.datasource_exchange import DatasourceExchange
from observability_charm_tools.exceptions import BlockedStatusError, WaitingStatusError
from observability_charm_tools.status_handling import StatusManager
from ops import Container, Port, pebble
from ops.pebble import Layer

from charm_config import CharmConfig
from workload_config import (
    AuthConfig,
    DeploymentConfig,
    ExternalServicesConfig,
    GrafanaConfig,
    KialiConfigSpec,
    PrometheusConfig,
    ServerConfig,
    TracingConfig,
    TracingTempoConfig,
)

LOGGER = logging.getLogger(__name__)
SOURCE_PATH = Path(__file__).parent


KIALI_CONFIG_PATH = Path("/kiali-configuration/config.yaml")
KIALI_PORT = 20001
KIALI_METRICS_PORT = 9090
KIALI_PEBBLE_SERVICE_NAME = "kiali"
ISTIO_RELATION = "istio-metadata"
PROMETHEUS_RELATION = "prometheus-api"
GRAFANA_RELATION = "grafana-metadata"
TEMPO_API_RELATION = "tempo-api"
TEMPO_DATASOURCE_EXCHANGE_RELATION = "tempo-datasource-exchange"


class GrafanaUrls(TypedDict):
    """A dictionary of Grafana URLs."""

    internal_url: str
    external_url: str


class TempoConfigurationData(TypedDict):
    """The configuration data for the Tempo datasource in Kiali."""

    datasource_uid: str
    external_url: str
    internal_url: str


class KialiCharm(ops.CharmBase):
    """Charm for managing Kiali."""

    def __init__(self, *args):
        super().__init__(*args)
        self._parsed_config = None

        self._container = self.unit.get_container("kiali")

        # O11y Integration
        self._scraping = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": [f"*:{KIALI_METRICS_PORT}"]}]}],
        )
        self._logging = LogForwarder(self)

        # Ingress Integration
        self._ingress = IngressPerAppRequirer(
            charm=self,
            port=KIALI_PORT,
            strip_prefix=False,
            redirect_https=True,
            scheme="http",
        )
        self.framework.observe(self._ingress.on.ready, self.reconcile)
        self.framework.observe(self._ingress.on.revoked, self.reconcile)

        # Connection to prometheus/grafana-source integration
        self._prometheus_source = PrometheusApiRequirer(self.model.relations, PROMETHEUS_RELATION)
        self.framework.observe(self.on[PROMETHEUS_RELATION].relation_changed, self.reconcile)
        self.framework.observe(self.on[PROMETHEUS_RELATION].relation_broken, self.reconcile)

        # Connection to the service mesh
        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                UnitPolicy(
                    relation="metrics-endpoint",
                    ports=[KIALI_METRICS_PORT],
                ),
            ],
        )

        # Connection to istio-k8s
        self._istio_metadata = IstioMetadataRequirer(self.model.relations, ISTIO_RELATION)
        self.framework.observe(self.on[ISTIO_RELATION].relation_changed, self.reconcile)
        self.framework.observe(self.on[ISTIO_RELATION].relation_broken, self.reconcile)

        self.framework.observe(self.on.kiali_pebble_ready, self.reconcile)
        self.framework.observe(self.on.config_changed, self.reconcile)
        self.framework.observe(self.on.start, self.reconcile)

        # Expose the Kiali workload through the service
        self.unit.set_ports(Port("tcp", KIALI_PORT))

        # Connection to the Grafana used for deep dives into the metrics from Kiali
        self._grafana_metadata = GrafanaMetadataRequirer(
            relation_mapping=self.model.relations, relation_name=GRAFANA_RELATION
        )
        self.framework.observe(self.on[GRAFANA_RELATION].relation_changed, self.reconcile)
        self.framework.observe(self.on[GRAFANA_RELATION].relation_broken, self.reconcile)

        # Integrating Tempo as a datasource for Kiali
        self._tempo_api = TempoApiRequirer(
            relation_mapping=self.model.relations, relation_name=TEMPO_API_RELATION
        )
        self.framework.observe(self.on[TEMPO_API_RELATION].relation_changed, self.reconcile)
        self.framework.observe(self.on[TEMPO_API_RELATION].relation_broken, self.reconcile)
        self._tempo_datasource_exchange = DatasourceExchange(
            charm=self,
            provider_endpoint=TEMPO_DATASOURCE_EXCHANGE_RELATION,
            requirer_endpoint=None,
        )
        self.framework.observe(
            self.on[TEMPO_DATASOURCE_EXCHANGE_RELATION].relation_changed, self.reconcile
        )
        self.framework.observe(
            self.on[TEMPO_DATASOURCE_EXCHANGE_RELATION].relation_broken, self.reconcile
        )

    def reconcile(self, _event: ops.ConfigChangedEvent):
        """Reconcile the entire state of the charm."""
        LOGGER.debug("Reconciling Kiali charm")
        status_manager = StatusManager()

        # Set a default value for any returns in the below context in case of an error
        prometheus_url = None
        with status_manager:
            prometheus_url = self._get_prometheus_source_url()

        istio_namespace = None
        with status_manager:
            istio_namespace = self._get_istio_namespace()

        grafana_internal_url = None
        grafana_external_url = None
        grafana_uid = None
        with status_manager:
            try:
                grafana_metadata = self._get_grafana_metadata()
                grafana_internal_url = str(grafana_metadata.direct_url)
                grafana_external_url = str(grafana_metadata.ingress_url)
                grafana_uid = grafana_metadata.grafana_uid
            except GrafanaMissingError:
                # Grafana integration is optional for the charm.  If the relation is Blocked (eg: does not exist) the
                # charm will log and ignore it.  But if the relation is Waiting, we catch the status normally.
                LOGGER.info("Grafana integration disabled - no grafana relation found.")

        tempo_configuration = None
        with status_manager:
            tempo_configuration = self._get_tempo_configuration(grafana_uid=grafana_uid)

        kiali_config = None
        with status_manager:
            kiali_config = self._generate_kiali_config(
                prometheus_url=prometheus_url,
                istio_namespace=istio_namespace,
                grafana_internal_url=grafana_internal_url,
                grafana_external_url=grafana_external_url,
                tempo_configuration=tempo_configuration,
            )

        with status_manager:
            self._configure_kiali_workload(kiali_config)

        with status_manager:
            _is_kiali_available(self._internal_url + self._prefix)

        # TODO: Log all statuses

        # Set the unit to be the worst status
        self.unit.status = status_manager.worst()

    def _configure_kiali_workload(self, new_config):
        """Configure the Kiali workload, if possible, logging errors otherwise.

        This will generate and push the Kiali configuration to the container, restarting the service if necessary.
        The purpose here is that this should always attempt to configure/start Kiali, but it does not guarantee Kiali is
        running after completion.  If any known errors occur, they will be logged and this method will return without
        error.  To confirm if Kiali is working, check the status of the Kiali workload directly.

        Args:
            new_config: The new configuration to push to the Kiali workload.  If None, the Kiali workload will be
                        stopped if it is currently running.
        """
        LOGGER.debug("Configuring Kiali workload")
        name = "kiali"
        if not self._container.can_connect():
            LOGGER.debug(f"Container is not ready, cannot configure {name}")
            raise WaitingStatusError("Container is not ready, cannot configure Kiali")

        if not new_config:
            try:
                self._container.get_service(KIALI_PEBBLE_SERVICE_NAME)
                self._container.stop(KIALI_PEBBLE_SERVICE_NAME)
            except ops.model.ModelError:
                # Service does not exist, so no need to stop it
                pass
            LOGGER.info(
                f"No new_config provided.  Stopping the {KIALI_PEBBLE_SERVICE_NAME} service if it is running."
            )
            return

        layer = self._generate_kiali_layer()
        new_config = yaml.dump(new_config)

        should_restart = not _is_container_file_equal_to(
            self._container, str(KIALI_CONFIG_PATH), new_config
        )
        self._container.push(KIALI_CONFIG_PATH, new_config, make_dirs=True)
        self._container.add_layer(name, layer, combine=True)
        self._container.autostart()

        if should_restart:
            LOGGER.info(f"new config detected for {name}, restarting the service")
            self._container.restart(KIALI_PEBBLE_SERVICE_NAME)

    def _generate_kiali_config(
        self,
        prometheus_url: Optional[str],
        istio_namespace: Optional[str],
        grafana_internal_url: Optional[str],
        grafana_external_url: Optional[str],
        tempo_configuration: Optional[TempoConfigurationData],
    ) -> dict:
        """Generate the Kiali configuration."""
        LOGGER.debug("Generating Kiali configuration")
        if not prometheus_url:
            raise BlockedStatusError("Cannot configure Kiali - no Prometheus url available")

        if not istio_namespace:
            raise BlockedStatusError("Cannot configure Kiali - no related istio available")

        external_services = ExternalServicesConfig(prometheus=PrometheusConfig(url=prometheus_url))

        if grafana_internal_url and grafana_external_url:
            LOGGER.info(
                "Grafana integration only works when connected to unauthenticated grafana instances."
            )
            # Kiali doesn't accept trailing slashes on grafana urls
            grafana_internal_url = grafana_internal_url.rstrip("/")
            grafana_external_url = grafana_external_url.rstrip("/")
            external_services.grafana = GrafanaConfig(
                enabled=True,
                internal_url=grafana_internal_url,
                external_url=grafana_external_url,
            )

        if tempo_configuration:
            external_services.tracing = TracingConfig(
                enabled=True,
                internal_url=tempo_configuration["internal_url"],
                external_url=tempo_configuration["external_url"],
                tempo_config=TracingTempoConfig(
                    org_id="1",
                    datasource_uid=tempo_configuration["datasource_uid"],
                    url_format="grafana",
                ),
            )

        kiali_config = KialiConfigSpec(
            auth=AuthConfig(strategy="anonymous"),
            deployment=DeploymentConfig(view_only_mode=self.parsed_config["view-only-mode"]),
            external_services=external_services,
            istio_namespace=istio_namespace,
            server=ServerConfig(port=KIALI_PORT, web_root=self._prefix),
        )

        returned = kiali_config.model_dump(exclude_none=True)
        LOGGER.debug(f"Kiali configuration: {returned}")
        return returned

    @staticmethod
    def _generate_kiali_layer() -> Layer:
        """Generate the Kiali layer."""
        # TODO: Add pebble checks?
        LOGGER.debug("Generating Kiali layer")
        layer = Layer(
            {
                "summary": "Kiali",
                "description": "The Kiali dashboard for Istio",
                "services": {
                    KIALI_PEBBLE_SERVICE_NAME: {
                        "override": "replace",
                        "summary": "kiali",
                        "command": f"/opt/kiali/kiali -config {KIALI_CONFIG_PATH}",
                        "startup": "enabled",
                        "working-dir": "/opt/kiali",
                    }
                },
            }
        )
        LOGGER.debug(f"Kiali layer: {layer}")
        return layer

    def _get_grafana_metadata(self) -> GrafanaMetadataAppData:
        """Return the metadata for the related Grafana.

        If ingress_url is not available, we default it to the direct_url.

        Raises:
          GrafanaMissingError: If no grafana is related to this application
          WaitingStatusError: If a grafana is related to this application, but its data is incomplete.
        """
        LOGGER.debug("Getting Grafana configuration")
        if len(self._grafana_metadata.relations) == 0:
            raise GrafanaMissingError("No grafana available over the grafana-metadata relation")

        grafana_metadata = self._grafana_metadata.get_data()
        if not grafana_metadata:
            raise WaitingStatusError("Waiting on data over the grafana-metadata relation")

        # Create the return object, including a default value for ingress_url
        grafana_metadata = GrafanaMetadataAppData(
            direct_url=grafana_metadata.direct_url,
            ingress_url=grafana_metadata.ingress_url or grafana_metadata.direct_url,
            grafana_uid=grafana_metadata.grafana_uid,
        )

        LOGGER.debug(f"Grafana metadata: {grafana_metadata}")
        return grafana_metadata

    def _get_istio_namespace(self) -> str:
        """Get the istio namespace configuration.

        Raises:
            BlockedStatusError: If no istio relation is available
            WaitingStatusError: If the istio relation is available, but the data is incomplete
        """
        LOGGER.debug("Getting Istio namespace")
        if len(self._istio_metadata.relations) == 0:
            raise BlockedStatusError("Missing required relation to istio provider")
        if not (istio_data := self._istio_metadata.get_data()):
            raise WaitingStatusError("Istio relation established, but data is missing or invalid")
        returned = istio_data.root_namespace
        LOGGER.debug(f"Istio namespace: {returned}")
        return returned

    def _get_prometheus_source_url(self) -> str:
        """Get the Prometheus source configuration.

        Returns, in this order, the first of:
        * prometheus's ingress_url
        * prometheus's direct_url

        Raises:
            BlockedStatusError: If no Prometheus sources are available
            WaitingStatusError: If Prometheus sources are available, but the data is incomplete
        """
        LOGGER.debug("Getting Prometheus source URL")
        if len(self._prometheus_source.relations) == 0:
            raise BlockedStatusError("Missing required relation to prometheus provider")
        if not (prometheus_data := self._prometheus_source.get_data()):
            raise WaitingStatusError(
                "Prometheus relation established, but data is missing or invalid"
            )
        # Return ingress_url if not None, else direct_url
        returned = str(prometheus_data.ingress_url or prometheus_data.direct_url)
        LOGGER.debug(f"Prometheus source URL: {returned}")
        return returned

    def _get_tempo_configuration(
        self, grafana_uid: Optional[str]
    ) -> Optional[TempoConfigurationData]:
        """Return configuration data for the related Tempo.

        This returns only the http api from tempo, not the grpc api, because Kiali only supports http.  If ingress_url
        is not available, we default it to the direct_url.

        Returns None if we are not related to a tempo.

        Raises:
          TempoMissingError: If no tempo is related to this application
          BlockedStatusError: If a tempo is related to this application, but something else that is required is missing.
          ConfigurationWaitingError: If a Tempo is related to this application, but its data sent from tempo or other
                                     required relations is incomplete.
        """
        try:
            tempo_metadata = self._get_tempo_api()
        except TempoMissingError:
            return None

        tempo_datasource_uid = self._get_tempo_datasource_uid(grafana_uid=grafana_uid)

        return TempoConfigurationData(
            internal_url=str(tempo_metadata.http.direct_url).rstrip("/"),
            external_url=str(
                tempo_metadata.http.ingress_url or tempo_metadata.http.direct_url
            ).rstrip("/"),
            datasource_uid=tempo_datasource_uid,
        )

    def _get_tempo_api(self) -> TempoApiAppData:
        """Get the Tempo api urls (internal and external).

        Raises:
            ConfigurationWaitingError: If a Tempo is related to this application, but its data is incomplete.
        """
        if len(self._tempo_api.relations) == 0:
            raise TempoMissingError("No tempo available over the tempo-api relation")

        tempo_metadata = self._tempo_api.get_data()
        if not tempo_metadata:
            raise WaitingStatusError("Waiting on related tempo application's metadata")

        return tempo_metadata

    def _get_tempo_datasource_uid(self, grafana_uid: Optional[str]) -> str:
        """Get the Tempo datasource uid.

        Returns the first related datasource that is a tempo datasource and has the same grafana uid as the known
        grafana.

        Will raise:
          ConfigurationBlockingError: If no applications are related, or applications are related but have sent only
                                       non-tempo datasources
          ConfigurationWaitingError: If a datasource is related, but has not yet provided data
        """
        if len(self.model.relations.get(TEMPO_DATASOURCE_EXCHANGE_RELATION, ())) == 0:
            raise BlockedStatusError(
                f"No tempo datasource available over the {TEMPO_DATASOURCE_EXCHANGE_RELATION} relation"
            )

        tempo_datasources = [
            datasource
            for datasource in self._tempo_datasource_exchange.received_datasources
            if datasource.type == "tempo"
        ]
        if len(tempo_datasources) == 0:
            WaitingStatusError("Tempo datasource relation exists, but no data has been provided")

        if not grafana_uid:
            raise BlockedStatusError(
                "Tempo datasource relation exists, but no grafana metadata is available.  Add a relation to Grafana on"
                " grafana-metadata unblock."
            )

        for datasource in tempo_datasources:
            if datasource.grafana_uid == grafana_uid:
                return datasource.uid
        raise BlockedStatusError(
            "Tempo datasources exist, but none match the related Grafana.  Check the that the "
            "grafana-metadata relation is related to the same Grafana as Tempo."
        )

    def _is_prometheus_source_available(self):
        """Return True if Prometheus is available, else False."""
        try:
            self._get_prometheus_source_url()
            return True
        except PrometheusSourceError:
            return False

    # Properties

    @property
    def parsed_config(self):
        """Return a validated and parsed configuration object."""
        if self._parsed_config is None:
            config = dict(self.model.config.items())
            self._parsed_config = CharmConfig(**config)  # pyright: ignore
        return self._parsed_config.model_dump(by_alias=True)

    @property
    def _prefix(self) -> str:
        """Return the prefix extracted from the external URL or '/' if the URL is None."""
        if self._ingress.url:
            return urlparse(self._ingress.url).path
        return "/"

    @property
    def _internal_url(self) -> str:
        """Return the fqdn dns-based in-cluster (private) address of kiali."""
        return f"http://localhost:{KIALI_PORT}"


# Helpers
def _is_container_file_equal_to(container: Container, filename: str, file_contents: str) -> bool:
    """Return True if the passed file_contents matches the filename inside the container, else False.

    Returns False if the container is not accessible, the file does not exist, or the contents do not match.
    """
    LOGGER.debug(f"Checking if {filename} in container is equal to passed contents")
    if not container.can_connect():
        LOGGER.debug(f"Container is not ready, cannot check {filename}")
        return False

    try:
        current_contents = container.pull(filename).read()
    except (pebble.ProtocolError, pebble.PathError) as e:
        LOGGER.warning(f"Could not check {filename} - got error while retrieving the file: {e}")
        return False

    returned = current_contents == file_contents
    LOGGER.debug(f"Result of current_contents == file_contents: {returned}")
    return returned


def _is_kiali_available(kiali_url):
    """Return True if the Kiali workload is available, else False."""
    # TODO: This feels like a pebble check.  We should move this to a pebble check, then just confirm pebble checks are
    #  passing
    try:
        if requests.get(url=kiali_url).status_code != 200:
            msg = (
                f"Kiali is not available at {kiali_url}- see other logs/statuses for reasons why."
                f"  If no other errors exist, this may be transient as the service starts."
            )
            raise WaitingStatusError(msg)
    except requests.exceptions.ConnectionError as e:
        msg = (
            f"Kiali is not available at {kiali_url} - got connection error: {e}."
            f"  If no other errors exist, this may be transient as the service starts."
        )
        raise WaitingStatusError(msg)
    return True


class PrometheusSourceError(Exception):
    """Raised when the Prometheus data is not available."""

    pass


class GrafanaMissingError(Exception):
    """Raised when the Grafana data is not available."""

    pass


class TempoMissingError(Exception):
    """Raised when the Grafana data is not available."""

    pass


if __name__ == "__main__":
    ops.main.main(KialiCharm)
