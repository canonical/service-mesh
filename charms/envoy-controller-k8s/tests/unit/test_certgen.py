# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""certgen tests — provisioning the control-plane secrets Envoy Gateway requires."""

from unittest.mock import patch

from conftest import make_state


def test_certgen_runs_in_model_namespace(ctx, krm_mocks):
    # GIVEN a reconcile that reaches the certgen step
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
