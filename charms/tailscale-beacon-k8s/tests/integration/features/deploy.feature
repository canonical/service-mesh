Feature: Charm deployment
  The tailscale-beacon-k8s charm deploys into a user application's model and
  creates LoadBalancer Services that a cluster-wide Tailscale operator exposes
  onto the tailnet.

  Background:
    Given a Juju Kubernetes model

  Scenario: Charm blocks without trust
    When the tailscale-beacon-k8s charm is deployed without trust
    Then the charm is blocked with message "Trust not granted. Run 'juju trust tailscale-beacon-k8s'"

  Scenario: Charm becomes active once trusted
    When the tailscale-beacon-k8s charm is deployed with trust
    Then the charm reaches active status

  Scenario: Charm stays active with no ingress relations
    Given the tailscale-beacon-k8s charm is deployed with trust and active
    Then the charm is active
    And no LoadBalancer Services exist for ingress
