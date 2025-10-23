Feature: Managed mode

  Background:
    Given an istio-system model with istio-k8s deployed
    And a juju model with bookinfo services

  Scenario: Authorization policies are created when managed mode is enabled
    Given the bookinfo services are deployed with istio
    And istio-beacon has manage-authorization-policies set to true
    Then istio-beacon has created authorization policies

  Scenario: Authorization policies are not created when managed mode is disabled
    Given the bookinfo services are deployed with istio
    And istio-beacon has manage-authorization-policies set to false
    Then istio-beacon has not created authorization policies
