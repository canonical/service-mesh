# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Control-plane Service regression tests.

Envoy Gateway hardcodes the proxy bootstrap to dial ``envoy-gateway.<ns>.svc`` on
the xDS/wasm ports, so the charm must publish a Service under that name selecting its
own pods — without it Gateways never reach Programmed=True.
"""

from conftest import make_state

import charm


def _reconciled_service(krm_mocks):
    krm_mocks.service.reconcile.assert_called_once()
    return krm_mocks.service.reconcile.call_args.args[0][0]


def test_control_plane_service_fronts_xds_and_wasm(ctx, krm_mocks):
    # GIVEN a default deployment
    state_in = make_state()
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), state_in)
    # THEN it publishes the envoy-gateway Service selecting the controller pods,
    # exposing the xDS and wasm ports the proxy bootstrap dials
    svc = _reconciled_service(krm_mocks)
    assert svc.metadata.name == charm.CONTROL_PLANE_NAME
    assert svc.metadata.namespace == state_in.model.name
    assert svc.spec.selector == {"app.kubernetes.io/name": "envoy-controller-k8s"}
    assert {p.port for p in svc.spec.ports} == {charm.XDS_PORT, charm.WASM_PORT}
