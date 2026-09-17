Feature: Workload scaling with tailnet ingress

  Background:
    Given a configured tailnet with an authenticated client
    And a juju model with tailscale-config and tailscale-k8s deployed
    And tailscale-k8s receives credentials from tailscale-config
    And a juju model for bookinfo services on the same cluster
    And tailscale-beacon-k8s is deployed in the bookinfo model
    And the bookinfo services are deployed with tailscale-beacon-k8s integration
    And productpage is reachable through its published ingress URL

  Scenario Outline: Productpage remains reachable when scaled from <initial_units> to <target_units> units
    Given productpage has <initial_units> units
    When you scale productpage to <target_units> units
    Then all charms are active
    And the published ingress URL for productpage is unchanged
    And productpage is reachable through its published ingress URL

    Examples:
      | initial_units | target_units |
      | 1             | 2            |
      | 2             | 1            |
