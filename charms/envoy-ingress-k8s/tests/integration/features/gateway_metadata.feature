Feature: Gateway metadata relation
  The envoy-ingress-k8s charm provides gateway-metadata to
  downstream consumers with Gateway information.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust and active
    And the envoy-ingress-k8s charm is deployed with trust and active

  Scenario: Gateway metadata is published when relation is established
    Given a charm that requires gateway-metadata is deployed
    When the gateway-metadata relation is established
    Then the gateway-metadata relation data contains the gateway name
    And the gateway-metadata relation data contains the gateway namespace
    And the gateway-metadata relation data contains listener addresses
