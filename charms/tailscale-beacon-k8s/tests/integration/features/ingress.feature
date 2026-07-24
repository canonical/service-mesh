Feature: Ingress relation
  The tailscale-beacon-k8s charm exposes requiring charms onto the tailnet by
  creating a LoadBalancer Service (loadBalancerClass: tailscale) per related
  app, which the Tailscale operator reconciles onto the tailnet.

  Background:
    Given a Juju Kubernetes model
    And a tailscale-k8s operator is running on the cluster
    And the tailscale-beacon-k8s charm is deployed with trust and active

  Scenario: Charm remains active without ingress relation
    Then the charm is active
    And no LoadBalancer Services exist for ingress

  Scenario: LoadBalancer Service is created when ingress relation is established
    Given a charm that requires ingress is deployed
    When the ingress relation is established
    Then a LoadBalancer Service exists for the requiring charm
    And the Service has loadBalancerClass "tailscale"
    And the Service is annotated with "tailscale.com/hostname" set to "<model>-<app>"
    And the Service selects the app pods on "app.kubernetes.io/name"
    And the Service exposes the app port

  Scenario: Ingress URL is published once the proxy is on the tailnet
    Given a charm that requires ingress is deployed
    And the ingress relation is established
    When the operator populates the Service tailnet address
    And the charm reaches active status
    Then the ingress URL "http://<tailnet-hostname>:<port>/" is published in the relation data
    And the ingress URL path is the root "/"
    And the charm status shows the tailnet hostname

  Scenario: LoadBalancer Service is removed when ingress relation is broken
    Given a charm that requires ingress is deployed
    And the ingress relation is established
    And the charm reaches active status
    When the ingress relation is removed
    And the charm reaches active status
    Then no LoadBalancer Services exist for the previously related charm

  Scenario: Multiple ingress relations create separate LoadBalancer Services
    Given productpage that requires ingress is deployed
    And productpage-b that requires ingress is deployed
    When the ingress relation is established with productpage
    And the ingress relation is established with productpage-b
    Then a LoadBalancer Service exists for productpage
    And a LoadBalancer Service exists for productpage-b
    And each Service is annotated with its own "tailscale.com/hostname"
