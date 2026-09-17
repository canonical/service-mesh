Feature: Tailnet deployment topology

  Background:
    Given a configured tailnet with an authenticated client
    And a juju model with tailscale-k8s deployed
    And a juju model for bookinfo services on the same cluster
    And tailscale-beacon-k8s is deployed in the bookinfo model

  Scenario: One beacon exposes multiple applications independently
    Given tailscale-config is deployed in the operator model
    And tailscale-k8s receives credentials from tailscale-config
    And productpage and productpage-b are exposed through the same tailscale-beacon-k8s
    When tailnet client requests GET /productpage on each application's published ingress URL
    Then each request succeeds
    And the applications have distinct published ingress URLs

  Scenario: Removing one application's ingress preserves the other application's ingress
    Given tailscale-config is deployed in the operator model
    And tailscale-k8s receives credentials from tailscale-config
    And productpage and productpage-b are exposed through the same tailscale-beacon-k8s
    When you remove the ingress relation between productpage and tailscale-beacon-k8s
    Then productpage has no published ingress URL
    And productpage-b is reachable through its published ingress URL

  Scenario: One operator exposes same-named applications in separate models
    Given tailscale-config is deployed in the operator model
    And tailscale-k8s receives credentials from tailscale-config
    And productpage is exposed through tailscale-beacon-k8s in each of two bookinfo models on the same cluster
    When tailnet client requests GET /productpage on each model's published ingress URL for productpage
    Then each request succeeds
    And productpage in each model has a distinct model-qualified ingress hostname

  Scenario: Removing ingress in one model preserves ingress in another model
    Given tailscale-config is deployed in the operator model
    And tailscale-k8s receives credentials from tailscale-config
    And productpage is exposed through tailscale-beacon-k8s in each of two bookinfo models on the same cluster
    When you remove the ingress relation for productpage in the first bookinfo model
    Then productpage in the first bookinfo model has no published ingress URL
    And productpage in the second bookinfo model is reachable through its published ingress URL

  Scenario: Cross-model credential distribution enables tailnet ingress
    Given tailscale-config is deployed in a separate juju model
    And tailscale-config has a granted root credential
    And the bookinfo services are deployed without tailscale-beacon-k8s integration
    And productpage has requested ingress from tailscale-beacon-k8s
    When you integrate tailscale-config with tailscale-k8s over tailscale-credentials across models
    Then tailscale-config has provisioned a credential for tailscale-k8s
    And productpage is reachable through its published ingress URL
