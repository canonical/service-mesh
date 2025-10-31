Feature: Istio service mesh integration

  Background:
    Given a juju model with istio-k8s deployed
    And a juju model for bookinfo services

  Scenario Outline: Bookinfo services can be deployed successfully <mesh_enabled>
    When you deploy the bookinfo services <mesh_enabled>
    Then all charms are active

    Examples:
      | mesh_enabled                          |
      | without istio-beacon-k8s integration  |
      | with istio-beacon-k8s integration     |

  Scenario Outline: Productpage can reach details <mesh_enabled>
    Given the bookinfo services are deployed <mesh_enabled>
    When productpage calls the details service
    Then the request succeeds
    And details returns valid book information

    Examples:
      | mesh_enabled                          |
      | without istio-beacon-k8s integration  |
      | with istio-beacon-k8s integration     |

  Scenario: Bookinfo services can be scaled without errors
    Given the bookinfo services are deployed with istio-beacon-k8s integration
    When you scale productpage to 2 units
    And you scale details to 2 units
    Then all charms are active
    When you scale productpage to 1 unit
    And you scale details to 1 unit
    Then all charms are active
