Feature: Extension server relation
  The envoy-controller-k8s charm is the requirer of the envoy-extension-server
  relation. When related to a provider (the envoy-ai-controller-k8s charm),
  it wires the provider's gRPC endpoint into Envoy Gateway's extensionManager
  and advertises its own control-plane identity back to the provider.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust
    And the charm reaches active status

  Scenario: Charm remains active without the extension-server relation
    Then the charm is active
    And no extensionManager is configured in the Envoy Gateway config

  Scenario: Extension manager is wired when related to the AI controller
    Given the envoy-ai-controller-k8s charm is deployed
    When the envoy-extension-server relation is established with envoy-ai-controller-k8s
    And the charm reaches active status
    Then the Envoy Gateway config contains an extensionManager entry
    And the extensionManager service fqdn matches the provider endpoint
    And the extensionManager xDS translator hooks are configured

  Scenario: Controller identity is published to the extension server
    Given the envoy-ai-controller-k8s charm is deployed
    When the envoy-extension-server relation is established with envoy-ai-controller-k8s
    And the charm reaches active status
    Then the envoy-extension-server relation data contains the controller name
    And the envoy-extension-server relation data contains the controller namespace

  Scenario: Extension manager is removed when the relation is broken
    Given the envoy-extension-server relation is established with envoy-ai-controller-k8s
    And the charm reaches active status
    When the envoy-extension-server relation is removed
    And the charm reaches active status
    Then no extensionManager is configured in the Envoy Gateway config
