Feature: Hardened mode

  Background:
    Given a juju model with istio-k8s deployed
    And a juju model for bookinfo services

  Scenario: Baseline - mesh traffic allowed without hardened mode when no policies exist
    Given istio-k8s has hardened-mode set to false
    And istio-k8s has auto-allow-waypoint-policy set to true
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to false
    When productpage requests GET /details/0 on details:9080
    Then the request succeeds

  Scenario: Hardened mode denies mesh traffic when no policies exist
    Given istio-k8s has hardened-mode set to true
    And istio-k8s has auto-allow-waypoint-policy set to true
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to false
    When productpage requests GET /details/0 on details:9080
    Then the request is forbidden

  Scenario: Baseline - app without inbound policy is reachable without hardened mode
    Given istio-k8s has hardened-mode set to false
    And istio-k8s has auto-allow-waypoint-policy set to true
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to true
    When details requests GET /productpage on productpage:9080
    Then the request succeeds

  Scenario: App without inbound policy is locked down with hardened mode
    Given istio-k8s has hardened-mode set to true
    And istio-k8s has auto-allow-waypoint-policy set to true
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to true
    When details requests GET /productpage on productpage:9080
    Then the request is forbidden

  Scenario: Allowed paths succeed with hardened mode when policies exist
    Given istio-k8s has hardened-mode set to true
    And istio-k8s has auto-allow-waypoint-policy set to true
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to true
    When productpage requests GET /health on details:9080
    Then the request succeeds
    When productpage requests GET /details/0 on details:9080
    Then the request succeeds

  # 503: waypoint cannot reach workloads at L4 when synthetic allow policy is removed
  Scenario: Traffic unavailable when auto-allow-waypoint-policy is disabled
    Given istio-k8s has hardened-mode set to true
    And istio-k8s has auto-allow-waypoint-policy set to false
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to true
    When productpage requests GET /details/0 on details:9080
    Then the request is unavailable

  Scenario: External traffic via ingress with hardened mode
    Given istio-k8s has hardened-mode set to true
    And istio-k8s has auto-allow-waypoint-policy set to true
    And istio-ingress-k8s is deployed
    And the bookinfo services are deployed with istio-beacon-k8s integration
    And istio-beacon-k8s has manage-authorization-policies set to true
    And productpage is exposed via ingress
    When external client requests GET /productpage on the ingress gateway
    Then the request succeeds
