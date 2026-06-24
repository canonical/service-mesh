Feature: ExtProc webhook management
  The envoy-controller-k8s charm manages the ExtProc sidecar injector
  MutatingWebhookConfiguration based on the enable-ai-gateway config.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the charm reaches active status

  Scenario: ExtProc webhook does not exist by default
    Then no MutatingWebhookConfiguration for ExtProc sidecar injection exists

  Scenario: ExtProc webhook is created when AI Gateway is enabled
    When the charm config enable-ai-gateway is set to "true"
    And the charm reaches active status
    Then a MutatingWebhookConfiguration for ExtProc sidecar injection exists
    And the webhook caBundle matches the CA from the tls-certificates relation

  Scenario: ExtProc webhook is removed when AI Gateway is disabled
    Given the charm config enable-ai-gateway is set to "true"
    And the charm reaches active status
    When the charm config enable-ai-gateway is set to "false"
    And the charm reaches active status
    Then no MutatingWebhookConfiguration for ExtProc sidecar injection exists
