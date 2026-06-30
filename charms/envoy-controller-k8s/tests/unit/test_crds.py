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
