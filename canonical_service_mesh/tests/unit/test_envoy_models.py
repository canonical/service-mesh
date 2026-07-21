# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for canonical_service_mesh envoy models.

These tests focus on serialisation shape — verifying that
``model_dump(by_alias=True, exclude_none=True)`` produces the exact JSON
structure that Envoy Gateway / Kubernetes expects.  Shape regressions (e.g.
renaming ``endpoint`` → ``host``/``port``) are caught here.
"""

from canonical_service_mesh.models import (
    AllowedRoutes,
    GatewayClassSpec,
    GatewaySpec,
    GatewayTLSConfig,
    Listener,
    ParametersRef,
    SecretObjectReference,
)
from canonical_service_mesh.models.envoy import (
    BackendEndpoint,
    BackendObjectRef,
    BackendSpec,
    EnvoyProxySpec,
    ExtAuth,
    ExtAuthHTTPService,
    FQDNEndpoint,
    JSONPatchOperation,
    LocalPolicyTargetRef,
    MetricsConfig,
    MetricSink,
    OpenTelemetrySink,
    ProxyBootstrap,
    SecurityPolicySpec,
    TelemetryConfig,
)

# ---- OpenTelemetry sink shape ----


def test_otel_sink_uses_host_and_port_not_endpoint():
    """Envoy Gateway metric sink schema requires host+port, not a URL."""
    sink = OpenTelemetrySink(host="otel.observability.svc", port=4318)
    data = sink.model_dump(by_alias=True)
    assert "host" in data and "port" in data
    assert "endpoint" not in data


def test_metric_sink_serialised_shape():
    """MetricSink serialises to the shape Envoy Gateway expects."""
    sink = MetricSink(openTelemetry=OpenTelemetrySink(host="collector", port=4318))
    data = sink.model_dump(by_alias=True, exclude_none=True)
    assert data == {
        "type": "OpenTelemetry",
        "openTelemetry": {"host": "collector", "port": 4318},
    }


def test_telemetry_config_omits_metrics_when_none():
    data = TelemetryConfig(metrics=None).model_dump(exclude_none=True)
    assert "metrics" not in data


# ---- EnvoyProxy spec — the full Juju-topology + OTLP shape ----


def test_envoy_proxy_spec_full_shape():
    """Full EnvoyProxy spec serialises correctly for KRM reconcile.

    Fixed stats tags are injected via a JSONPatch on the Envoy bootstrap, since
    the EnvoyProxy CRD has no native stats-tags field — the only schema-valid way
    to add them is patching the bootstrap's ``stats_config.stats_tags``.
    """
    spec = EnvoyProxySpec(
        bootstrap=ProxyBootstrap(
            type="JSONPatch",
            jsonPatches=[
                JSONPatchOperation(
                    op="add",
                    path="/stats_config/stats_tags/-",
                    value={"tag_name": "juju_model", "fixed_value": "my-model"},
                ),
                JSONPatchOperation(
                    op="add",
                    path="/stats_config/stats_tags/-",
                    value={"tag_name": "juju_charm", "fixed_value": "envoy-controller-k8s"},
                ),
            ],
        ),
        telemetry=TelemetryConfig(
            metrics=MetricsConfig(
                sinks=[MetricSink(openTelemetry=OpenTelemetrySink(host="otel", port=4318))]
            )
        ),
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)

    assert data["bootstrap"]["type"] == "JSONPatch"
    patches = data["bootstrap"]["jsonPatches"]
    assert all(p["op"] == "add" for p in patches)
    assert all(p["path"] == "/stats_config/stats_tags/-" for p in patches)
    tags = {p["value"]["tag_name"]: p["value"]["fixed_value"] for p in patches}
    assert tags == {
        "juju_model": "my-model",
        "juju_charm": "envoy-controller-k8s",
    }
    assert data["telemetry"]["metrics"]["sinks"][0]["openTelemetry"]["host"] == "otel"


def test_envoy_proxy_spec_omits_telemetry_when_no_otlp():
    """When OTLP is not related, telemetry must be absent from the spec."""
    spec = EnvoyProxySpec(
        bootstrap=ProxyBootstrap(
            type="JSONPatch",
            jsonPatches=[
                JSONPatchOperation(
                    op="add",
                    path="/stats_config/stats_tags/-",
                    value={"tag_name": "juju_model", "fixed_value": "m"},
                )
            ],
        )
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    assert "telemetry" not in data


# ---- Backend spec ----


def test_backend_spec_fqdn_shape():
    """Backend spec serialises external hostname correctly for SecurityPolicy backendRef."""
    spec = BackendSpec(
        endpoints=[BackendEndpoint(fqdn=FQDNEndpoint(hostname="auth.example.com", port=4180))]
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    assert data == {"endpoints": [{"fqdn": {"hostname": "auth.example.com", "port": 4180}}]}


# ---- SecurityPolicy spec ----


def test_security_policy_spec_full_shape():
    """SecurityPolicy with extAuth serialises to the shape Envoy Gateway expects."""
    spec = SecurityPolicySpec(
        targetRef=LocalPolicyTargetRef(
            group="gateway.networking.k8s.io",
            kind="Gateway",
            name="envoy-ingress",
        ),
        extAuth=ExtAuth(
            http=ExtAuthHTTPService(
                backendRefs=[
                    BackendObjectRef(
                        group="gateway.envoyproxy.io",
                        kind="Backend",
                        name="forward-auth-backend",
                        namespace="default",
                    )
                ],
                path="/check",
            )
        ),
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    assert data["targetRef"] == {
        "group": "gateway.networking.k8s.io",
        "kind": "Gateway",
        "name": "envoy-ingress",
    }
    assert data["extAuth"]["http"]["backendRefs"][0]["name"] == "forward-auth-backend"
    assert data["extAuth"]["http"]["path"] == "/check"


def test_security_policy_spec_omits_ext_auth_when_none():
    spec = SecurityPolicySpec(
        targetRef=LocalPolicyTargetRef(
            group="gateway.networking.k8s.io", kind="Gateway", name="gw"
        )
    )
    data = spec.model_dump(exclude_none=True)
    assert "extAuth" not in data


def test_backend_object_ref_omits_namespace_when_none():
    ref = BackendObjectRef(group="gateway.envoyproxy.io", kind="Backend", name="b")
    data = ref.model_dump(exclude_none=True)
    assert "namespace" not in data


# ---- Gateway model additions ----


def test_gateway_class_spec_with_parameters_ref():
    """GatewayClassSpec with parametersRef pointing at EnvoyProxy serialises correctly."""
    spec = GatewayClassSpec(
        controllerName="gateway.envoyproxy.io/gatewayclass-controller",
        parametersRef=ParametersRef(
            group="gateway.envoyproxy.io",
            kind="EnvoyProxy",
            name="envoy-default",
            namespace="envoy-gateway-system",
        ),
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    assert data["controllerName"] == "gateway.envoyproxy.io/gatewayclass-controller"
    assert data["parametersRef"]["name"] == "envoy-default"
    assert data["parametersRef"]["namespace"] == "envoy-gateway-system"


def test_gateway_class_spec_omits_parameters_ref_when_none():
    spec = GatewayClassSpec(controllerName="gateway.envoyproxy.io/gatewayclass-controller")
    data = spec.model_dump(exclude_none=True)
    assert "parametersRef" not in data


def test_gateway_spec_http_listener_shape():
    """GatewaySpec with HTTP listener serialises correctly for KRM reconcile."""
    spec = GatewaySpec(
        gatewayClassName="envoy",
        listeners=[
            Listener(
                name="http",
                port=80,
                protocol="HTTP",
                allowedRoutes=AllowedRoutes(namespaces={"from": "All"}),
            )
        ],
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    assert data["gatewayClassName"] == "envoy"
    assert data["listeners"][0]["port"] == 80
    assert "parametersRef" not in data


def test_gateway_spec_https_listener_includes_tls_secret():
    spec = GatewaySpec(
        gatewayClassName="envoy",
        listeners=[
            Listener(
                name="https",
                port=443,
                protocol="HTTPS",
                allowedRoutes=AllowedRoutes(namespaces={"from": "All"}),
                tls=GatewayTLSConfig(
                    certificateRefs=[
                        SecretObjectReference(kind="Secret", name="my-tls", namespace="default")
                    ]
                ),
            )
        ],
    )
    data = spec.model_dump(by_alias=True, exclude_none=True)
    cert = data["listeners"][0]["tls"]["certificateRefs"][0]
    assert cert["name"] == "my-tls"
    assert cert["namespace"] == "default"
