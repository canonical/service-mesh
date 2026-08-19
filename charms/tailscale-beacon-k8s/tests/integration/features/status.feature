Feature: Status reporting for exposed apps
  Once an app is related, the tailscale-beacon-k8s charm reports status by
  reading the signals the operator writes back onto the beacon's own
  LoadBalancer Service: .status.loadBalancer.ingress and the TailscaleProxyReady
  condition.

  Background:
    Given a Juju Kubernetes model
    And a tailscale-k8s operator is running on the cluster
    And the tailscale-beacon-k8s charm is deployed with trust and active
    And a charm that requires ingress is deployed
    And the ingress relation is established

  Scenario: Waiting while the proxy is coming up
    When the operator sets TailscaleProxyReady to "ProxyPending" on the Service
    Then the charm is waiting
    And the charm status surfaces the operator's TailscaleProxyReady message

  Scenario: Active once the tailnet address is populated
    When the operator populates the Service tailnet address
    Then the charm reaches active status
    And the charm status shows the tailnet hostname

  Scenario: Error when the proxy reports a terminal failure
    When the operator sets TailscaleProxyReady to "ProxyFailed" on the Service
    Then the charm goes to error
    And the operator's TailscaleProxyReady message is surfaced as the error
    And other reconcile operations complete before the error is raised

  Scenario: Warning about device approval when pending past the timeout
    When the proxy stays "ProxyPending" past the configured ready-timeout
    Then the charm remains waiting
    And a warning about possible device approval "NeedsMachineAuth" is logged
