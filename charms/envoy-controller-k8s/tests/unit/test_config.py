# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Envoy Gateway config-generation regression tests for the controller charm."""

import yaml
from conftest import make_state

import charm


def _render_config(ctx, krm_mocks, **state_kwargs) -> dict:
    with ctx(ctx.on.config_changed(), make_state(**state_kwargs)) as mgr:
        return yaml.safe_load(mgr.charm._construct_envoy_gateway_config())


def _envoy_proxy_spec(ctx, krm_mocks, **state_kwargs) -> dict:
    with ctx(ctx.on.config_changed(), make_state(**state_kwargs)) as mgr:
        return mgr.charm._construct_envoy_proxy().spec


def test_log_level_propagates_to_config(ctx, krm_mocks):
    # GIVEN a non-default log level
    # WHEN the controller config is rendered
    cfg = _render_config(ctx, krm_mocks, config={"log-level": "debug"})
    # THEN it is reflected in the Envoy Gateway logging config
    assert cfg["envoyGateway"]["logging"]["level"]["default"] == "debug"


def test_extension_apis_always_enabled(ctx, krm_mocks):
    # Backend + EnvoyPatchPolicy are required by the AI extension server and are kept
    # enabled unconditionally (see Discussion Points in specs/envoy.spec.md).
    cfg = _render_config(ctx, krm_mocks)
    assert cfg["envoyGateway"]["extensionApis"] == {
        "enableEnvoyPatchPolicy": True,
        "enableBackend": True,
    }


def test_no_otlp_sink_without_relation(ctx, krm_mocks):
    # GIVEN no OTLP relation
    # WHEN the config is rendered
    cfg = _render_config(ctx, krm_mocks)
    # THEN no control-plane telemetry sink is configured
    assert "telemetry" not in cfg["envoyGateway"]


def test_otlp_sink_configured_when_related(ctx, krm_mocks):
    # GIVEN an OTLP endpoint over the relation
    # WHEN the config is rendered
    cfg = _render_config(ctx, krm_mocks, otlp_endpoint="http://collector:4317")
    # THEN the Envoy Gateway OpenTelemetry metric sink targets the parsed host and port
    sinks = cfg["envoyGateway"]["telemetry"]["metrics"]["sinks"]
    assert len(sinks) == 1
    assert sinks[0]["openTelemetry"]["host"] == "collector"
    assert sinks[0]["openTelemetry"]["port"] == 4317


def test_otlp_sink_defaults_to_grpc_port(ctx, krm_mocks):
    # GIVEN an OTLP endpoint with no explicit port
    # WHEN the config is rendered
    cfg = _render_config(ctx, krm_mocks, otlp_endpoint="http://collector")
    # THEN the sink falls back to the OTLP/gRPC default (4317), not the HTTP default
    # — EG's OpenTelemetry sink exports over gRPC.
    sinks = cfg["envoyGateway"]["telemetry"]["metrics"]["sinks"]
    assert sinks[0]["openTelemetry"]["port"] == 4317


def test_envoy_proxy_carries_juju_topology_stats_tags(ctx, krm_mocks):
    # EnvoyProxy has no native stats-tags field, so the Juju topology is stamped onto
    # proxy metrics by JSON-patching the bootstrap stats_config.stats_tags.
    spec = _envoy_proxy_spec(ctx, krm_mocks)
    patches = spec["bootstrap"]["jsonPatches"]
    assert {p["value"]["tag_name"] for p in patches} == {
        "juju_model",
        "juju_model_uuid",
        "juju_application",
        "juju_charm",
    }
    assert all(p["path"] == "/stats_config/stats_tags/-" for p in patches)


def test_envoy_proxy_has_no_telemetry_without_otlp(ctx, krm_mocks):
    # GIVEN no OTLP relation, THEN the proxy carries no telemetry sink
    spec = _envoy_proxy_spec(ctx, krm_mocks)
    assert "telemetry" not in spec


def test_envoy_proxy_telemetry_sink_when_related(ctx, krm_mocks):
    # GIVEN an OTLP endpoint, THEN the proxy's OpenTelemetry sink targets host and port
    spec = _envoy_proxy_spec(ctx, krm_mocks, otlp_endpoint="http://collector:4317")
    sink = spec["telemetry"]["metrics"]["sinks"][0]
    assert sink["openTelemetry"]["host"] == "collector"
    assert sink["openTelemetry"]["port"] == 4317


def test_gateway_class_binds_controller_and_default_envoy_proxy(ctx, krm_mocks):
    # The shared "envoy" GatewayClass carries the Envoy Gateway controllerName and a
    # parametersRef to the default EnvoyProxy, so proxies inherit its config cross-model.
    with ctx(ctx.on.config_changed(), make_state()) as mgr:
        gc = mgr.charm._construct_gateway_class()
        app_name, model_name = mgr.charm.app.name, mgr.charm.model.name
    assert gc.metadata.name == charm.GATEWAY_CLASS_NAME
    assert gc.spec["controllerName"] == charm.ENVOY_GATEWAY_CONTROLLER_NAME
    ref = gc.spec["parametersRef"]
    assert ref["kind"] == charm.ENVOY_PROXY_KIND
    assert (ref["name"], ref["namespace"]) == (app_name, model_name)


def test_config_change_alters_layer_hash(ctx, krm_mocks):
    # Envoy Gateway does not hot-reload config.yaml and replan() only restarts on layer
    # changes, so a config hash is stamped into the layer env to force a restart.
    with ctx(ctx.on.config_changed(), make_state(config={"log-level": "info"})) as mgr:
        info_env = mgr.charm._construct_gateway_layer().services["envoy-gateway"].environment
    with ctx(ctx.on.config_changed(), make_state(config={"log-level": "debug"})) as mgr:
        debug_env = mgr.charm._construct_gateway_layer().services["envoy-gateway"].environment
    assert info_env["EG_CONFIG_HASH"] != debug_env["EG_CONFIG_HASH"]
