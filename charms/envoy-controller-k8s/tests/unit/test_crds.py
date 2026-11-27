# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""CRD reconciliation regression tests for the controller charm."""

from unittest.mock import patch

from conftest import make_state

import charm
from charm import EnvoyControllerCharm


def test_control_plane_crds_applied(ctx, krm_mocks):
    # GIVEN a default deployment
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), make_state())
    # THEN the Gateway API, Envoy Gateway, and GIE CRDs are applied
    for scope in (charm.GATEWAY_API_SCOPE, charm.ENVOY_GATEWAY_SCOPE, charm.GIE_SCOPE):
        krm_mocks.crd[scope].reconcile.assert_called_once()


def test_reconcile_halts_until_crds_established(ctx, krm_mocks):
    # GIVEN the CRDs are applied but not yet Established in the cluster
    with patch.object(EnvoyControllerCharm, "_crds_established", return_value=False):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state())
    # THEN it does not start the controller against unregistered schemas:
    # the EnvoyProxy is never reconciled
    krm_mocks.proxy.reconcile.assert_not_called()


def test_gateway_api_crds_skipped_when_externally_managed(ctx, krm_mocks):
    # GIVEN another charm (e.g. istio-k8s) provides the Gateway API CRDs
    state = make_state(config={"manage-gateway-api-crds": False})
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), state)
    # THEN the charm never even constructs the Gateway API CRD manager...
    assert charm.GATEWAY_API_SCOPE not in krm_mocks.crd
    # ...but still applies the CRDs only it provides, and starts the controller
    for scope in (charm.ENVOY_GATEWAY_SCOPE, charm.GIE_SCOPE):
        krm_mocks.crd[scope].reconcile.assert_called_once()
    krm_mocks.proxy.reconcile.assert_called_once()

