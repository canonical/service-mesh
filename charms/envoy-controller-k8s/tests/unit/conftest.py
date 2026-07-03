# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ops
import pytest
import scenario
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Secret

import charm
from charm import EnvoyControllerCharm

# Minimal plan so scenario's consistency checker accepts a 'readiness' check status
# on the input container (a CheckInfo requires the check to exist in the plan).
_GATEWAY_LAYER = ops.pebble.Layer(
    {
        "services": {"envoy-gateway": {"override": "replace", "command": "envoy-gateway"}},
        "checks": {
            "readiness": {
                "override": "replace",
                "level": "ready",
                "startup": "enabled",
                "threshold": 3,
            }
        },
    }
)

CA_PEM = "CAPEM"
CERT_PEM = "CERTPEM"
KEY_PEM = "KEYPEM"

DEFAULT_ENVOY_GATEWAY_IMAGE = "docker.io/envoyproxy/gateway:v1.7.0"

# oci-image resources surface to the charm as a YAML file holding the image reference
# under `registrypath`. Materialise those files once so make_state can hand scenario a
# real resource path (scenario refuses to fetch a resource absent from State).
_RES_DIR = Path(tempfile.mkdtemp())


def _image_resource(name: str, ref: str) -> scenario.Resource:
    path = _RES_DIR / f"{name}-{abs(hash(ref))}.yaml"
    path.write_text(f"registrypath: {ref}\n")
    return scenario.Resource(name=name, path=path)

# The certgen-issued control-plane Secret, as lightkube returns it: a TLS Secret
# named "envoy-gateway" whose data values are base64-encoded PEM (Secret wire format).
CONTROL_PLANE_SECRET = Secret(
    metadata=ObjectMeta(name=charm.CONTROL_PLANE_NAME),
    type="kubernetes.io/tls",
    data={
        "tls.crt": base64.b64encode(CERT_PEM.encode()).decode(),
        "tls.key": base64.b64encode(KEY_PEM.encode()).decode(),
        "ca.crt": base64.b64encode(CA_PEM.encode()).decode(),
    },
)


@pytest.fixture()
def ctx():
    return scenario.Context(EnvoyControllerCharm)


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Mock the charm's lightkube Client.

    Defaults: trusted (list returns []) and the certgen control-plane Secret present
    (get returns it), so reconcile reaches the cert push and Service steps.
    """
    with patch("charm.Client") as client_cls:
        instance = client_cls.return_value
        instance.list.return_value = []
        instance.get.return_value = CONTROL_PLANE_SECRET
        yield instance


@pytest.fixture()
def krm_mocks():
    """Replace the KRM factories with mocks and treat CRDs as Established.

    Yields a namespace with:
      - ``crd``: dict of scope -> KRM mock (populated as the charm calls _crd_krm)
      - ``proxy``: the EnvoyProxy KRM mock
      - ``service``: the control-plane Service KRM mock
      - ``gateway_class``: the shared GatewayClass KRM mock
      - ``foreign_owner``: the _foreign_gateway_class_owner mock (defaults to None, i.e.
        no pre-existing foreign "envoy" class; set return_value to a str to simulate one)
    """
    crd: dict = {}

    def crd_factory(scope):
        return crd.setdefault(scope, MagicMock())

    with patch.object(EnvoyControllerCharm, "_crd_krm", side_effect=crd_factory), patch.object(
        EnvoyControllerCharm, "_envoy_proxy_krm"
    ) as proxy, patch.object(
        EnvoyControllerCharm, "_control_plane_service_krm"
    ) as service, patch.object(
        EnvoyControllerCharm, "_gateway_class_krm"
    ) as gateway_class, patch.object(
        EnvoyControllerCharm, "_foreign_gateway_class_owner", return_value=None
    ) as foreign_owner, patch.object(
        EnvoyControllerCharm, "_crds_established", return_value=True
    ):
        yield SimpleNamespace(
            crd=crd,
            proxy=proxy.return_value,
            service=service.return_value,
            gateway_class=gateway_class.return_value,
            foreign_owner=foreign_owner,
        )


def make_state(
    *,
    can_connect: bool = True,
    config: dict | None = None,
    gateway_checks=frozenset(),
    planned_units: int = 1,
    leader: bool = True,
    otlp_endpoint: str | None = None,
    extension_server: bool = False,
    extension_server_fqdn: str | None = "ai.envoy-test.svc.cluster.local",
    extension_server_port: str | None = "1063",
    envoy_gateway_image: str = DEFAULT_ENVOY_GATEWAY_IMAGE,
) -> scenario.State:
    """Build a State for the controller charm with sensible defaults.

    Set ``extension_server=True`` to add the relation. Pass ``extension_server_fqdn``
    /``extension_server_port`` as None to model a related-but-not-yet-published provider.
    """
    relations = set()
    if extension_server:
        remote = {}
        if extension_server_fqdn is not None:
            remote["extension_server_fqdn"] = json.dumps(extension_server_fqdn)
        if extension_server_port is not None:
            remote["extension_server_port"] = json.dumps(extension_server_port)
        relations.add(
            scenario.Relation(
                "envoy-extension-server",
                interface="envoy_extension_server",
                remote_app_data=remote,
            )
        )
    if otlp_endpoint:
        relations.add(
            scenario.Relation(
                "otlp",
                interface="otlp",
                remote_app_data={
                    "endpoints": json.dumps(
                        [
                            {
                                "endpoint": otlp_endpoint,
                                "protocol": "grpc",
                                "telemetries": ["metrics"],
                                "insecure": True,
                            }
                        ]
                    )
                },
            )
        )
    containers = {
        scenario.Container(
            "envoy-gateway",
            can_connect=can_connect,
            check_infos=gateway_checks,
            layers={"envoy-gateway": _GATEWAY_LAYER} if gateway_checks else {},
            execs={
                scenario.Exec(
                    ["envoy-gateway", "certgen", "--disable-topology-injector"],
                    return_code=0,
                )
            },
        ),
    }
    return scenario.State(
        leader=leader,
        planned_units=planned_units,
        relations=relations,
        containers=containers,
        config=config or {},
        resources={_image_resource("envoy-gateway-image", envoy_gateway_image)},
    )
