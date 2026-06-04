Feature: TLS certificates relation
  The envoy-ingress-k8s charm uses tls-certificates for
  Gateway HTTPS listeners.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust and active
    And the envoy-ingress-k8s charm is deployed with trust and active

  Scenario: Charm remains active without certificates relation
    Then the charm is active
    And the Gateway has only HTTP listeners

  Scenario: HTTPS listener is configured when certificates relation is established
    Given the self-signed-certificates charm is deployed
    When the certificates relation is established with self-signed-certificates
    And the charm reaches active status
    Then the Gateway has an HTTPS listener
    And the HTTPS listener references a TLS Secret
