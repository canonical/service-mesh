Feature: Authorization policies

  Background:
    Given a juju model with istio-k8s deployed
    And a juju model for bookinfo services
    And the bookinfo services are deployed with istio-beacon-k8s integration

  Scenario: Allowed paths and methods are permitted
    When productpage requests GET /health on details:9080
    Then the request succeeds
    When productpage requests GET /details/0 on details:9080
    Then the request succeeds

  Scenario: Disallowed methods are forbidden
    When productpage requests POST /details/0 on details:9080
    Then the request is forbidden
    When productpage requests PUT /details/0 on details:9080
    Then the request is forbidden
    When productpage requests DELETE /details/0 on details:9080
    Then the request is forbidden

  Scenario: Disallowed paths are forbidden
    When productpage requests GET /admin on details:9080
    Then the request is forbidden
    When productpage requests GET /unauthorized on details:9080
    Then the request is forbidden

  Scenario: Disallowed ports are rejected
    When productpage requests GET /details/0 on details:8080
    Then the request is rejected
    When productpage requests GET /health on details:8080
    Then the request is rejected
