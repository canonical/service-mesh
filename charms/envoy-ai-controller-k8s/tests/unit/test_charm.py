# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Status-model and lifecycle regression tests for the AI controller charm."""

import base64
import dataclasses
from pathlib import Path
from unittest.mock import patch

import httpx
import ops
import pytest
import scenario
import yaml
from conftest import make_state
from lightkube import ApiError

import charm
from charm import EnvoyAiControllerCharm


def _api_error(code: int) -> ApiError:
    request = httpx.Request("GET", "http://localhost")
    response = httpx.Response(code, json={"message": "x", "code": code}, request=request)
    return ApiError(request=request, response=response)


def test_blocked_without_trust(ctx, mock_lightkube_client):
    # GIVEN a trusted-cluster probe that is denied (charm not run with --trust)
    mock_lightkube_client.list.side_effect = _api_error(403)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it blocks telling the operator exactly how to fix it
    assert state_out.unit_status == ops.BlockedStatus(
        "Trust not granted. Run 'juju trust envoy-ai-controller-k8s'"
    )


def test_invalid_log_level_falls_back_to_default(ctx, krm_mocks):
    # GIVEN a log-level outside the accepted enum
    # WHEN the config is rendered
    with ctx(ctx.on.config_changed(), make_state(config={"log-level": "verbose"})) as mgr:
        # THEN the bad value never reaches the controller's -logLevel flag; info is used
        assert mgr.charm._log_level == "info"
    # AND the unit stays active rather than blocking on the typo
    state_out = ctx.run(ctx.on.config_changed(), make_state(config={"log-level": "verbose"}))
    assert state_out.unit_status == ops.ActiveStatus()


def test_waiting_without_pebble(ctx):
    # GIVEN the workload container is not yet reachable
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state(can_connect=False))
    # THEN it waits for Pebble
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for Pebble (ai-gateway container)"
    )


def test_blocked_without_certificates_relation(ctx):
    # GIVEN no certificates relation (the webhook serving cert has no source)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state(certificates=False))
    # THEN it blocks on the missing relation
    assert state_out.unit_status == ops.BlockedStatus("Missing relation: certificates")


def test_waiting_when_certificate_not_yet_issued(ctx, certs_absent):
    # GIVEN the certificates relation is present but no cert has been issued yet
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it waits for the certificate
    assert state_out.unit_status == ops.WaitingStatus("Waiting for TLS certificate")


def test_blocked_without_extension_server_relation(ctx, krm_mocks):
    # GIVEN trust, Pebble, certs — but no Envoy Gateway relating in (the AI on/off switch)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state(extension_server=False))
    # THEN it blocks: the controller is useless without an EG control plane to extend
    assert state_out.unit_status == ops.BlockedStatus(
        "Missing relation: envoy-extension-server"
    )


def test_active_when_all_preconditions_met(ctx, krm_mocks):
    # GIVEN trust, Pebble, certs, and the extension-server relation
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it is active
    assert state_out.unit_status == ops.ActiveStatus()


def test_maintenance_while_crds_not_established(ctx, krm_mocks):
    # GIVEN the CRDs are applied but not yet Established, so reconcile halts before
    # the controller service is added to the plan
    with patch.object(EnvoyAiControllerCharm, "_crds_established", return_value=False):
        # WHEN the charm reconciles and status is collected
        state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it reports maintenance rather than falsely reporting Active
    assert state_out.unit_status == ops.MaintenanceStatus(
        "Setting up Envoy AI Gateway control plane"
    )


def test_reconcile_defers_on_api_429(ctx, krm_mocks):
    # GIVEN a freshly-Established CRD whose storage backend is still initializing —
    # the first list against a CR of that CRD returns 429 "storage is (re)initializing".
    # This is a known k8s race window between Established=True and the CRD's aggregated
    # storage actually serving; crashing the hook would flip the unit to error and flake
    # deploy pipelines that assert "no error was ever seen."
    krm_mocks.webhook.reconcile.side_effect = _api_error(429)
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state())
    # THEN it returns cleanly (maintenance, not error) — the next event re-runs reconcile
    assert state_out.unit_status == ops.MaintenanceStatus(
        "Setting up Envoy AI Gateway control plane"
    )


def test_waiting_when_controller_health_check_fails(ctx, krm_mocks):
    # GIVEN the controller readiness check is failing (alive but not serving)
    failing = frozenset(
        {
            scenario.CheckInfo(
                name="readiness",
                level=ops.pebble.CheckLevel.READY,
                status=ops.pebble.CheckStatus.DOWN,
            )
        }
    )
    # WHEN the charm reconciles
    state_out = ctx.run(ctx.on.config_changed(), make_state(controller_checks=failing))
    # THEN it reports waiting, not active. Only liveness is restart-wired, so a sustained
    # readiness failure stays in waiting rather than restart-looping.
    assert state_out.unit_status == ops.WaitingStatus(
        "Waiting for AI Gateway controller to become healthy"
    )


def test_extension_server_address_published_when_related(ctx, krm_mocks):
    # GIVEN the extension-server relation is present
    with patch.object(charm.ExtensionServerProvider, "publish_data") as publish:
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN it advertises its Extension Server gRPC endpoint to the EG control plane
    publish.assert_called_once()
    kwargs = publish.call_args.kwargs
    assert kwargs["extension_server_fqdn"].startswith("envoy-ai-controller-k8s.")
    assert kwargs["extension_server_fqdn"].endswith(".svc.cluster.local")
    assert kwargs["extension_server_port"] == "1063"


def test_webhook_uses_issuing_ca_as_ca_bundle(ctx, krm_mocks):
    # The API server validates the webhook cert against caBundle, so caBundle must be the
    # CA that issued the served cert.
    with ctx(ctx.on.config_changed(), make_state()) as mgr:
        webhook = mgr.charm._construct_webhook("CAPEM")
        # The controller patches a hardcoded-named config at startup and exits if it is
        # missing, so the name must match the upstream constant exactly.
        assert (
            webhook.metadata.name
            == f"envoy-ai-gateway-gateway-pod-mutator.{mgr.charm.model.name}"
        )
    assert base64.b64decode(webhook.webhooks[0].clientConfig.caBundle) == b"CAPEM"
    assert webhook.webhooks[0].clientConfig.service.path == "/mutate"
    assert webhook.webhooks[0].clientConfig.service.port == 9443


def test_webhook_scoped_to_envoy_gateway_pods(ctx, krm_mocks):
    # The webhook must only intercept Envoy Gateway data-plane pods. Matching all pods
    # would catch the controller's own pod and deadlock its (re)creation.
    with ctx(ctx.on.config_changed(), make_state()) as mgr:
        webhook = mgr.charm._construct_webhook("CAPEM")
    assert webhook.webhooks[0].objectSelector.matchLabels == {
        "app.kubernetes.io/managed-by": "envoy-gateway"
    }


def test_unexpected_api_error_is_not_swallowed(ctx, mock_lightkube_client):
    # GIVEN the trust probe fails with a non-auth error (API unreachable, 500, ...)
    mock_lightkube_client.list.side_effect = _api_error(500)
    # WHEN trust is evaluated
    with ctx(ctx.on.update_status(), make_state()) as mgr:
        # THEN the error surfaces rather than being misreported as "untrusted"
        with pytest.raises(ApiError):
            _ = mgr.charm._trusted
        # Reset so the manager's implicit exit-time reconcile sees a healthy client.
        mock_lightkube_client.list.side_effect = None


def test_remove_deletes_webhook_only_when_last_unit_leaves(ctx):
    # GIVEN this is the final unit of the application
    with patch.object(EnvoyAiControllerCharm, "_webhook_krm") as webhook:
        # WHEN the unit is removed
        ctx.run(ctx.on.remove(), make_state(planned_units=0))
    # THEN the cluster-scoped ExtProc webhook is cleaned up (Juju owns the Service)
    webhook.return_value.delete.assert_called_once()


def test_remove_keeps_webhook_on_scale_down(ctx):
    # GIVEN peer units of the application remain
    with patch.object(EnvoyAiControllerCharm, "_webhook_krm") as webhook:
        # WHEN this unit is removed
        ctx.run(ctx.on.remove(), make_state(planned_units=1))
    # THEN the shared webhook is left in place for the surviving units
    webhook.return_value.delete.assert_not_called()


def test_webhook_removed_on_extension_server_relation_broken(ctx, krm_mocks):
    # Regression: without teardown on relation-broken, the MutatingWebhookConfiguration
    # would linger and keep intercepting Envoy Gateway data-plane pod CREATEs against a
    # Service with no useful backend (stale controller, or failurePolicy=Fail blocking
    # pod creation outright).
    ext_server = scenario.Relation(
        "envoy-extension-server", interface="envoy_extension_server"
    )
    state = make_state(extension_server=False)
    state = dataclasses.replace(state, relations=state.relations | {ext_server})
    # WHEN the envoy-extension-server relation breaks
    ctx.run(ctx.on.relation_broken(ext_server), state)
    # THEN the ExtProc webhook is reconciled to the empty set (idempotent delete)
    krm_mocks.webhook.reconcile.assert_called_once_with([])


@pytest.mark.parametrize(
    "ref, expected",
    [
        # Normal tagged reference -> the tag is the version.
        ("docker.io/envoyproxy/ai-gateway-controller:v0.6.0", "v0.6.0"),
        # Registry with a port: the host ':port' must not be mistaken for a tag.
        ("registry.example.com:5000/ns/ai-gateway-controller:1.2.3", "1.2.3"),
        # Digest-pinned, no tag: fall back to DEFAULT_TAG (the version this charm
        # build was aligned with). Charmhub's OCI mirror strips the tag from the
        # URL, so this branch is the norm for charmhub-published deploys.
        (
            "docker.io/envoyproxy/ai-gateway-controller@sha256:" + "a" * 64,
            charm.DEFAULT_TAG,
        ),
    ],
)
def test_workload_version_from_image_tag(ctx, ref, expected):
    # The controller binary self-reports no version, so the deployed image tag is the
    # source of truth when parseable, else DEFAULT_TAG carries the pin forward.
    with ctx(ctx.on.config_changed(), make_state(ai_gateway_image=ref)) as mgr:
        assert mgr.charm._workload_version == expected


@pytest.mark.parametrize(
    "controller_ref, config_override, expected",
    [
        # Default: derive the extproc tag from the controller image tag against the
        # upstream repo. This is the fix for the ImagePullBackOff — Juju cannot mint
        # pull creds for an image not attached to a container, so the extproc URL
        # must resolve outside Juju's private registry.
        (
            "docker.io/envoyproxy/ai-gateway-controller:v0.6.0",
            "",
            "docker.io/envoyproxy/ai-gateway-extproc:v0.6.0",
        ),
        # Digest-pinned controller (no tag) — derive from DEFAULT_TAG. Explicit
        # pin, not the upstream binary's unpinned :latest baked-in default
        # (which reports version=dev and mismatches the controller's config).
        (
            "docker.io/envoyproxy/ai-gateway-controller@sha256:" + "a" * 64,
            "",
            f"docker.io/envoyproxy/ai-gateway-extproc:{charm.DEFAULT_TAG}",
        ),
        # Config override wins over derivation, for air-gapped / custom-mirror deploys.
        (
            "docker.io/envoyproxy/ai-gateway-controller:v0.6.0",
            "mirror.example.com/extproc:custom",
            "mirror.example.com/extproc:custom",
        ),
    ],
)
def test_extproc_image_ref(ctx, controller_ref, config_override, expected):
    state = make_state(
        ai_gateway_image=controller_ref,
        config={"extproc-image": config_override},
    )
    with ctx(ctx.on.config_changed(), state) as mgr:
        assert mgr.charm._extproc_image_ref == expected


def test_default_tag_matches_charmcraft_upstream_source():
    # DEFAULT_TAG is the fallback used when the ai-gateway-image URL is digest-only
    # (charmhub-mirrored deploys). It must match the tag the charm build was packed
    # against so the two never drift on version bumps.
    charmcraft_yaml = (
        Path(__file__).parent.parent.parent / "charmcraft.yaml"
    ).read_text()
    upstream_source = yaml.safe_load(charmcraft_yaml)["resources"][
        "ai-gateway-image"
    ]["upstream-source"]
    _, _, tag = upstream_source.rpartition(":")
    assert tag == charm.DEFAULT_TAG


def test_pebble_layer_sets_extproc_otlp_env_when_related(ctx):
    # The relation endpoint is a base URL; the charm must append /v1/metrics because
    # the signal-specific OTel env var is used verbatim by the SDK (no path appended,
    # unlike the generic OTEL_EXPORTER_OTLP_ENDPOINT).
    state = make_state(otlp_endpoint="http://collector:4318")
    with ctx(ctx.on.config_changed(), state) as mgr:
        command = mgr.charm._construct_pebble_layer().services["ai-gateway"].command
    assert (
        "--extProcExtraEnvVars=OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="
        "http://collector:4318/v1/metrics" in command
    )


def test_pebble_layer_has_no_otlp_env_without_relation(ctx):
    with ctx(ctx.on.config_changed(), make_state()) as mgr:
        command = mgr.charm._construct_pebble_layer().services["ai-gateway"].command
    assert "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT" not in command


@pytest.mark.parametrize(
    "value, expected_flag",
    [
        # Default mapping: without it gen_ai metrics carry no per-caller attribute.
        (
            "x-user-id:user.id",
            "--metricsRequestHeaderAttributes=x-user-id:user.id",
        ),
        # Invalid value falls back to the default instead of reaching the controller,
        # which would exit at startup on a bad mapping.
        (
            "not a mapping",
            "--metricsRequestHeaderAttributes=x-user-id:user.id",
        ),
        # Empty disables header mapping entirely — the flag is omitted.
        ("", None),
    ],
)
def test_metrics_header_attributes_flag(ctx, value, expected_flag):
    state = make_state(config={"metrics-request-header-attributes": value})
    with ctx(ctx.on.config_changed(), state) as mgr:
        command = mgr.charm._construct_pebble_layer().services["ai-gateway"].command
    if expected_flag is None:
        assert "--metricsRequestHeaderAttributes" not in command
    else:
        assert expected_flag in command


def test_certificate_request_omits_cn_and_covers_fqdn_san(ctx):
    # GIVEN a long Juju model name that pushes the service FQDN past the 64-char X.509
    # CN limit (regression: the charm crashed in certificates-relation-created when the
    # FQDN was used as the CN under pytest-jubilant's long generated model names).
    long_model = scenario.Model(name="test-controllers-7b72fb3c")
    state = dataclasses.replace(make_state(), model=long_model)
    with ctx(ctx.on.config_changed(), state) as mgr:
        request = mgr.charm._certificate_request
        fqdn = mgr.charm._service_fqdn
    # THEN no CN is set (the spec requires CN to match a SAN, so we omit it) and the FQDN
    # is a SAN, where the API server actually validates the webhook cert.
    assert len(fqdn) > 64
    assert not request.common_name
    assert fqdn in request.sans_dns
