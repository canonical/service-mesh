Feature: Charm deployment
  The envoy-controller-k8s charm deploys and reaches active status
  with all required relations established.

  Background:
    Given a Juju Kubernetes model

  Scenario: Charm deploys and reaches active status
    Given the self-signed-certificates charm is deployed
    When the envoy-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    Then the charm reaches active status

  Scenario: Charm blocks without trust
    Given the self-signed-certificates charm is deployed
    When the envoy-controller-k8s charm is deployed without trust
    And the certificates relation is established with self-signed-certificates
    Then the charm is blocked with message "Trust not granted — run 'juju trust envoy-controller-k8s'"

  Scenario: Charm blocks without certificates relation
    When the envoy-controller-k8s charm is deployed with trust
    Then the charm is blocked with message "Missing relation: certificates"
