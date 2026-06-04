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

  Scenario: HTTPRoute is removed when ingress relation is broken
    Given the ingress relation is established
    And the charm reaches active status
    When the ingress relation is removed
    And the charm reaches active status
    Then no HTTPRoutes exist for the previously related charm

  Scenario: Multiple ingress relations create separate HTTPRoutes
    Given charm-a that requires ingress is deployed
    And charm-b that requires ingress is deployed
    When the ingress relation is established with charm-a
    And the ingress relation is established with charm-b
    And the charm reaches active status
    Then an HTTPRoute exists for charm-a
    And an HTTPRoute exists for charm-b

  Scenario: Conflicting routes from different models are rejected
    Given charm "b-c" in model "a" requests ingress with path "/a-b-c/"
    And charm "c" in model "a-b" requests ingress with path "/a-b-c/"
    When both ingress relations are established
    Then no HTTPRoutes are created for the conflicting charms
    And the charm is blocked with a message indicating a route conflict
