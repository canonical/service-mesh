Feature: Controller workloads
  The envoy-controller-k8s charm runs Envoy Gateway and optionally
  AI Gateway controllers as Pebble workload containers.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the charm reaches active status

  Scenario: Only Envoy Gateway controller is running by default
    Then the envoy-gateway Pebble service is running
    And the ai-gateway Pebble service is not running

  Scenario: AI Gateway controller starts when enabled
    When the charm config enable-ai-gateway is set to "true"
    And the charm reaches active status
    Then the envoy-gateway Pebble service is running
    And the ai-gateway Pebble service is running

  Scenario: AI Gateway controller stops when disabled again
    Given the charm config enable-ai-gateway is set to "true"
    And the charm reaches active status
    When the charm config enable-ai-gateway is set to "false"
    And the charm reaches active status
    Then the envoy-gateway Pebble service is running
    And the ai-gateway Pebble service is not running
