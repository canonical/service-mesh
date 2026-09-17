Feature: Tailnet credential management

  Background:
    Given a configured tailnet with an authenticated client
    And a juju model with tailscale-config and tailscale-k8s deployed
    And a juju model for bookinfo services on the same cluster
    And tailscale-beacon-k8s is deployed in the bookinfo model
    And the bookinfo services are deployed without tailscale-beacon-k8s integration
    And productpage has requested ingress from tailscale-beacon-k8s

  Scenario: Relation-provided credentials enable tailnet ingress
    Given tailscale-config has a granted root credential
    When you integrate tailscale-config with tailscale-k8s over tailscale-credentials
    Then tailscale-config has provisioned a credential for tailscale-k8s
    And productpage is reachable through its published ingress URL

  Scenario: Supplying a missing root credential enables credential provisioning
    Given tailscale-config has no root credential configured
    And tailscale-config is integrated with tailscale-k8s over tailscale-credentials
    And tailscale-config has not provisioned a credential for tailscale-k8s
    When you grant and configure a valid root credential for tailscale-config
    Then tailscale-config has provisioned a credential for tailscale-k8s
    And all charms are active
    And productpage is reachable through its published ingress URL

  Scenario: Removing the credentials relation revokes the operator credential
    Given tailscale-k8s receives credentials from tailscale-config
    And productpage is reachable through its published ingress URL
    And the ingress relation for productpage has been removed
    And the tailnet proxy for productpage has been removed
    When you remove the tailscale-credentials relation between tailscale-config and tailscale-k8s
    Then the credential provisioned for tailscale-k8s is revoked on the control server
    And tailscale-k8s is blocked
