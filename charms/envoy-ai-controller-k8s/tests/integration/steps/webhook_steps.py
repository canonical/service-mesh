# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""ExtProc webhook steps for the envoy-ai-controller-k8s suite."""

from jubilant import Juju
from pytest_bdd import then

from tests.integration.helpers import WEBHOOK_PORT, get_ext_proc_webhook


@then("a MutatingWebhookConfiguration for ExtProc sidecar injection exists")
def webhook_exists(juju: Juju) -> None:
    """Assert the ExtProc MutatingWebhookConfiguration is present on the cluster."""
    assert get_ext_proc_webhook(juju.model) is not None


@then("the ExtProc webhook targets the pod-mutation path on the webhook port")
def webhook_client_config(juju: Juju) -> None:
    """Assert the webhook dials the /mutate path on the webhook Service port."""
    webhook = get_ext_proc_webhook(juju.model)
    assert webhook is not None
    service = webhook.webhooks[0].clientConfig.service
    assert service.path == "/mutate"
    assert service.port == WEBHOOK_PORT


@then("the ExtProc webhook selects only envoy-gateway managed pods")
def webhook_object_selector(juju: Juju) -> None:
    """Assert the webhook's objectSelector scopes it to envoy-gateway managed pods."""
    webhook = get_ext_proc_webhook(juju.model)
    assert webhook is not None
    labels = webhook.webhooks[0].objectSelector.matchLabels
    assert labels == {"app.kubernetes.io/managed-by": "envoy-gateway"}


@then("the ExtProc webhook caBundle is populated")
def webhook_ca_bundle(juju: Juju) -> None:
    """Assert the webhook caBundle is populated from the certificates relation."""
    webhook = get_ext_proc_webhook(juju.model)
    assert webhook is not None
    assert webhook.webhooks[0].clientConfig.caBundle
