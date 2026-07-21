Feature: Charm deployment
  The envoy-ai-controller-k8s charm deploys and reaches active status once it
  is trusted and both required relations -- certificates and
  envoy-extension-server -- are established.

  Background:
    Given a Juju Kubernetes model

  # Scenarios in this feature share one module-scoped model and run top-to-bottom.
  # This must stay the first scenario: trust cannot be revoked within a run, so the
  # untrusted (blocked) state can only be observed before any later scenario grants it.
  Scenario: Charm blocks without trust
    When the envoy-ai-controller-k8s charm is deployed without trust
    Then the charm is blocked with message "Trust not granted. Run 'juju trust envoy-ai-controller-k8s'"

  Scenario: Charm blocks without the certificates relation
    When the envoy-ai-controller-k8s charm is deployed with trust
    Then the charm is blocked with message "Missing relation: certificates"

  Scenario: Charm blocks without the extension-server relation
    Given the self-signed-certificates charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    When the certificates relation is established with self-signed-certificates
    Then the charm is blocked with message "Missing relation: envoy-extension-server"

  Scenario: Charm reaches active status with all relations
    Given the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    When the envoy-extension-server relation is established with envoy-controller-k8s
    Then the charm reaches active status
