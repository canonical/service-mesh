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


def _certgen_calls(mock_exec):
    """Return exec calls whose command starts with `envoy-gateway certgen`."""
    return [
        call for call in mock_exec.call_args_list
        if call.args and call.args[0][:2] == ["envoy-gateway", "certgen"]
    ]


def _stub_exec(mock_exec):
    """Make wait_output/wait return sane values so the mock does not break unpacking.

    The charm also runs `envoy-gateway version` under this same patch (workload
    version source); without a stubbed return, ``wait_output()`` yields a MagicMock
    that ``stdout, _ =`` cannot unpack.
    """
    mock_exec.return_value.wait_output.return_value = ("", "")
    mock_exec.return_value.wait.return_value = None


def test_certgen_runs_in_model_namespace(ctx, krm_mocks, mock_lightkube_client):
    # GIVEN the control-plane Secret does not exist yet
    mock_lightkube_client.get.side_effect = _not_found()
    # WHEN the charm runs certgen, THEN it targets the model namespace, not the
    # upstream default 'envoy-gateway-system' (which does not exist → certgen fails).
    with patch("ops.Container.exec") as mock_exec:
        _stub_exec(mock_exec)
        with ctx(ctx.on.config_changed(), make_state()) as mgr:
            mgr.run()
            expected_ns = mgr.charm.model.name

    certgen_calls = _certgen_calls(mock_exec)
    assert len(certgen_calls) == 1
    assert certgen_calls[0].args[0] == [
        "envoy-gateway",
        "certgen",
        "--disable-topology-injector",
    ]
    assert certgen_calls[0].kwargs["environment"] == {
        "ENVOY_GATEWAY_NAMESPACE": expected_ns
    }


def test_certgen_skipped_when_secret_present(ctx, krm_mocks):
    # GIVEN the control-plane Secret already exists (conftest default)
    # WHEN the charm reconciles
    with patch("ops.Container.exec") as mock_exec:
        _stub_exec(mock_exec)
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN certgen is not re-run — it is idempotent but re-running on every event
    # (incl. 5-minute update-status) risks a transient exec failure tipping the
    # charm into error state.
    assert _certgen_calls(mock_exec) == []


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
        _stub_exec(mock_exec)
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN certgen re-runs rather than skipping forever on a partial Secret set —
    # the guard requires ALL CERTGEN_SECRETS, not just 'envoy-gateway'.
    assert len(_certgen_calls(mock_exec)) == 1
