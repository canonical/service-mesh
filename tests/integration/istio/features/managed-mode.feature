Feature: Managed mode

  Background:
    Given a juju model with istio-k8s deployed
    And a juju model for bookinfo services

  Scenario: Authorization policies are created when managed mode is enabled
    Given the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to true
    Then istio-beacon-k8s has created authorization policies

  Scenario: Authorization policies are not created when managed mode is disabled
    Given the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to false
    Then istio-beacon-k8s has not created authorization policies
