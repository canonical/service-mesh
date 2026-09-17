Feature: Tailnet ingress

  Background:
    Given a configured tailnet with an authenticated client
    And a juju model with tailscale-config and tailscale-k8s deployed
    And tailscale-k8s receives credentials from tailscale-config
    And a juju model for bookinfo services on the same cluster
    And tailscale-beacon-k8s is deployed in the bookinfo model

  Scenario: Bookinfo with tailnet ingress can be deployed successfully
    When you deploy the bookinfo services with tailscale-beacon-k8s integration
    Then all charms are active
    And productpage is reachable through its published ingress URL

  Scenario: Productpage is exposed at the root path on the default ingress port
    Given the bookinfo services are deployed with tailscale-beacon-k8s integration
    When tailnet client requests GET /productpage on the published ingress URL for productpage
    Then the request succeeds
    And productpage returns the book information page
    And productpage has a published ingress URL with port 80 and path /

  Scenario Outline: Productpage can reach details <ingress_enabled>
    Given the bookinfo services are deployed <ingress_enabled>
    When productpage calls the details service
    Then the request succeeds
    And details returns valid book information

    Examples:
      | ingress_enabled                         |
      | without tailscale-beacon-k8s integration |
      | with tailscale-beacon-k8s integration    |

  Scenario: Exposing productpage preserves cluster-local access
    Given the bookinfo services are deployed with tailscale-beacon-k8s integration
    When details requests GET /productpage on productpage:9080
    Then the request succeeds
    And productpage returns the book information page

  Scenario: Changing the ingress port updates tailnet access
    Given tailscale-beacon-k8s has listen-port set to 80
    And the bookinfo services are deployed with tailscale-beacon-k8s integration
    When you set listen-port on tailscale-beacon-k8s to 8080
    Then productpage has a published ingress URL with port 8080 and path /
    And productpage is reachable through its published ingress URL

  Scenario: Removing ingress withdraws tailnet access
    Given productpage and productpage-b are exposed through the same tailscale-beacon-k8s
    And productpage is reachable through its published ingress URL
    When you remove the ingress relation between productpage and tailscale-beacon-k8s
    Then productpage has no published ingress URL
    And the previous ingress URL for productpage is no longer reachable
    And productpage-b is reachable through its published ingress URL

  Scenario: Recreating ingress restores tailnet access
    Given the bookinfo services were exposed through tailscale-beacon-k8s
    And the ingress relation for productpage has been removed
    When you integrate productpage with tailscale-beacon-k8s over ingress
    Then all charms are active
    And productpage is reachable through its published ingress URL

  Scenario Outline: Tailnet ingress recovers after restarting <component>
    Given the bookinfo services are deployed with tailscale-beacon-k8s integration
    And productpage is reachable through its published ingress URL
    When you restart <component>
    Then the published ingress URL for productpage is unchanged
    And productpage is reachable through its published ingress URL

    Examples:
      | component                        |
      | the tailscale-k8s operator        |
      | the tailnet proxy for productpage |
