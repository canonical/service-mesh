Feature: Useless without an operator
  The tailscale-beacon-k8s charm only creates Kubernetes resources. Without a
  tailscale-k8s operator running somewhere on the cluster, the LoadBalancer
  Service it creates is never reconciled onto the tailnet. This coupling is by
  design: the operator is the single tailnet authority for the cluster.

  Background:
    Given a Juju Kubernetes model
    And no tailscale-k8s operator is running on the cluster
    And the tailscale-beacon-k8s charm is deployed with trust and active

  Scenario: Idle beacon is active even without an operator
    Then the charm is active
    And no LoadBalancer Services exist for ingress

  Scenario: Exposed app cannot reach the tailnet without an operator
    Given a charm that requires ingress is deployed
    When the ingress relation is established
    Then a LoadBalancer Service exists for the requiring charm
    But the Service tailnet address is never populated
    And the charm does not publish an ingress URL
    And the charm goes to error after the ready-timeout elapses
