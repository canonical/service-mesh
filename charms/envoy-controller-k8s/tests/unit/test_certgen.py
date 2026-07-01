# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""certgen tests — provisioning the control-plane secrets Envoy Gateway requires."""

from unittest.mock import patch

import httpx
from conftest import CONTROL_PLANE_SECRET, make_state
from lightkube import ApiError


def _not_found() -> ApiError:
    request = httpx.Request("GET", "http://localhost")
    response = httpx.Response(404, json={"message": "x", "code": 404}, request=request)
    return ApiError(request=request, response=response)


def test_certgen_runs_in_model_namespace(ctx, krm_mocks, mock_lightkube_client):
    # GIVEN the control-plane Secret does not exist yet
    mock_lightkube_client.get.side_effect = _not_found()
    # WHEN the charm runs certgen, THEN it targets the model namespace, not the
    # upstream default 'envoy-gateway-system' (which does not exist → certgen fails).
    with patch("ops.Container.exec") as mock_exec:
        with ctx(ctx.on.config_changed(), make_state()) as mgr:
            mgr.run()
            expected_ns = mgr.charm.model.name

    mock_exec.assert_called_once()
    assert mock_exec.call_args.args[0] == [
        "envoy-gateway",
        "certgen",
        "--disable-topology-injector",
    ]
    assert mock_exec.call_args.kwargs["environment"] == {
        "ENVOY_GATEWAY_NAMESPACE": expected_ns
    }


def test_certgen_skipped_when_secret_present(ctx, krm_mocks):
    # GIVEN the control-plane Secret already exists (conftest default)
    # WHEN the charm reconciles
    with patch("ops.Container.exec") as mock_exec:
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN certgen is not re-run — it is idempotent but re-running on every event
    # (incl. 5-minute update-status) risks a transient exec failure tipping the
    # charm into error state.
    mock_exec.assert_not_called()


def test_certgen_runs_when_any_secret_is_missing(ctx, krm_mocks, mock_lightkube_client):
    # GIVEN the load-bearing 'envoy' Secret is absent but 'envoy-gateway' is present
    # (e.g. certgen interrupted mid-exec, or one Secret deleted out-of-band)
    def get(_resource, name, namespace):
        if name == "envoy":
            raise _not_found()
        return CONTROL_PLANE_SECRET

    mock_lightkube_client.get.side_effect = get
    # WHEN the charm reconciles
    with patch("ops.Container.exec") as mock_exec:
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN certgen re-runs rather than skipping forever on a partial Secret set —
    # the guard requires ALL CERTGEN_SECRETS, not just 'envoy-gateway'.
    mock_exec.assert_called_once()
