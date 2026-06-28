# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""CRD reconciliation regression tests for the controller charm."""

from unittest.mock import patch

from conftest import make_state

import charm
from charm import EnvoyControllerCharm


def test_ai_gateway_crds_applied_when_enabled(ctx, krm_mocks):
    # GIVEN AI Gateway is enabled
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), make_state(config={"enable-ai-gateway": True}))
    # THEN the AI Gateway CRDs are applied, never torn down
    ai_krm = krm_mocks.crd[charm.AI_GATEWAY_SCOPE]
    ai_krm.reconcile.assert_called_once()
    ai_krm.delete.assert_not_called()


def test_ai_gateway_crds_removed_when_disabled(ctx, krm_mocks):
    # GIVEN AI Gateway is disabled (default)
    # WHEN the charm reconciles
    ctx.run(ctx.on.config_changed(), make_state(config={"enable-ai-gateway": False}))
    # THEN the AI Gateway CRDs are torn down, never applied
    ai_krm = krm_mocks.crd[charm.AI_GATEWAY_SCOPE]
    ai_krm.delete.assert_called_once()
    ai_krm.reconcile.assert_not_called()


def test_reconcile_halts_until_crds_established(ctx, krm_mocks):
    # GIVEN the CRDs are applied but not yet Established in the cluster
    with patch.object(EnvoyControllerCharm, "_crds_established", return_value=False):
        # WHEN the charm reconciles
        ctx.run(ctx.on.config_changed(), make_state(config={"enable-ai-gateway": True}))
    # THEN it does not start controllers against unregistered schemas:
    # the webhook and EnvoyProxy are never reconciled
    krm_mocks.webhook.reconcile.assert_not_called()
    krm_mocks.proxy.reconcile.assert_not_called()
