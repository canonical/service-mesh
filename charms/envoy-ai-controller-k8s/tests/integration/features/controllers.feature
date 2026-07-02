Feature: Controller workload
  The envoy-ai-controller-k8s charm runs the Envoy AI Gateway controller as a
  Pebble workload container.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: Envoy AI Gateway controller is running
    Then the ai-gateway Pebble service is running
