Feature: Scaling
  The envoy-ai-controller-k8s charm supports horizontal scaling with all units
  behaving identically.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: Charm scales to multiple units
    When the charm is scaled to 2 units
    Then all units reach active status
    And the ai-gateway Pebble service is running on all units

  Scenario: CRDs and webhook remain consistent after scaling
    When the charm is scaled to 3 units
    And all units reach active status
    Then the AI Gateway CRDs exist on the cluster
    And a MutatingWebhookConfiguration for ExtProc sidecar injection exists

  Scenario: Charm scales back down
    Given the charm is scaled to 2 units
    And all units reach active status
    When the charm is scaled to 1 unit
    Then all units reach active status
