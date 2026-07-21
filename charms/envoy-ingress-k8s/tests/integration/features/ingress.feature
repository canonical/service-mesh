Feature: Ingress relation
  The envoy-ingress-k8s charm provides ingress for requiring charms
  by creating HTTPRoutes through the Gateway.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust and active
    And the envoy-ingress-k8s charm is deployed with trust and active

  Scenario: Charm remains active without ingress relation
    Then the charm is active
    And no HTTPRoutes exist for ingress

  Scenario: HTTPRoute is created when ingress relation is established
    Given a charm that requires ingress is deployed
    When the ingress relation is established
    And the charm reaches active status
    Then an HTTPRoute exists for the requiring charm
    And the HTTPRoute references the Gateway
    And the ingress URL is published in the relation data
    And traffic to the ingress URL returns 200

  Scenario: HTTPRoute is removed when ingress relation is broken
    Given the ingress relation is established
    And the charm reaches active status
    When the ingress relation is removed
    And the charm reaches active status
    Then no HTTPRoutes exist for the previously related charm

  Scenario: Multiple ingress relations create separate HTTPRoutes
    Given productpage that requires ingress is deployed
    And productpage-b that requires ingress is deployed
    When the ingress relation is established with productpage
    And the ingress relation is established with productpage-b
    And the charm reaches active status
    Then an HTTPRoute exists for productpage
    And an HTTPRoute exists for productpage-b
