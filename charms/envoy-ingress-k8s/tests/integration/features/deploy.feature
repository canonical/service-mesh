Feature: Charm deployment
  The envoy-ingress-k8s charm deploys and manages GatewayClass
  and Gateway resources for Envoy Gateway.

  Background:
    Given a Juju Kubernetes model

  Scenario: Charm waits when controller is not available
    When the envoy-ingress-k8s charm is deployed with trust
    Then the charm is waiting with message "Waiting for GatewayClass controller to become available"

  Scenario: Charm reaches active when controller is available
    Given the envoy-controller-k8s charm is deployed with trust and active
    When the envoy-ingress-k8s charm is deployed with trust
    Then the charm reaches active status

  Scenario: Charm blocks without trust
    Given the envoy-controller-k8s charm is deployed with trust and active
    When the envoy-ingress-k8s charm is deployed without trust
    Then the charm is blocked with message "Trust not granted — run 'juju trust envoy-ingress-k8s'"
