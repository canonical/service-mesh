# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""ExtProc webhook contract regression tests."""

import base64

from conftest import CA_PEM, make_state

import charm

APP = "envoy-controller-k8s"


def test_webhook_points_at_control_plane_service_when_ai_enabled(ctx, krm_mocks):
    # GIVEN AI Gateway is enabled
    state_in = make_state(config={"enable-ai-gateway": True})
    model = state_in.model.name
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), state_in)
    # THEN the ExtProc webhook routes admission to the control-plane Service, whose
    # certgen-issued cert SANs are envoy-gateway.* so the served cert validates
    krm_mocks.webhook.reconcile.assert_called_once()
    config = krm_mocks.webhook.reconcile.call_args.args[0][0]
    client = config.webhooks[0].clientConfig
    assert client.service.name == charm.CONTROL_PLANE_NAME
    assert client.service.namespace == model
    assert client.service.port == charm.WEBHOOK_PORT
    assert client.service.path == "/mutate"
    # caBundle is a K8s []byte field: base64-encoded PEM. The certgen Secret's ca.crt
    # is already base64(PEM), so it is the caBundle value verbatim.
    assert client.caBundle == base64.b64encode(CA_PEM.encode()).decode()


def test_webhook_removed_when_ai_disabled(ctx, krm_mocks):
    # GIVEN AI Gateway is disabled (default)
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), make_state(config={"enable-ai-gateway": False}))
    # THEN the ExtProc webhook is torn down, never created
    krm_mocks.webhook.delete.assert_called_once()
    krm_mocks.webhook.reconcile.assert_not_called()
