Feature: Forward auth relation
  The envoy-ingress-k8s charm configures external authentication
  via the forward-auth relation.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust and active
    And the envoy-ingress-k8s charm is deployed with trust and active

  Scenario: Charm remains active without forward-auth relation
    Then the charm is active
    And no SecurityPolicy with extAuth exists

  Scenario: SecurityPolicy is created when forward-auth relation is established
    Given a charm that provides forward-auth is deployed
    When the forward-auth relation is established
    And the charm reaches active status
    Then a SecurityPolicy with extAuth exists
    And the extAuth target matches the forward-auth relation data

  Scenario: SecurityPolicy is removed when forward-auth relation is broken
    Given the forward-auth relation is established
    And the charm reaches active status
    When the forward-auth relation is removed
    And the charm reaches active status
    Then no SecurityPolicy with extAuth exists
