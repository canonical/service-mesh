Feature: Controller workloads
  The envoy-controller-k8s charm runs the Envoy Gateway controller as a
  Pebble workload container.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust
    And the charm reaches active status

  Scenario: Envoy Gateway controller is running
    Then the envoy-gateway Pebble service is running
