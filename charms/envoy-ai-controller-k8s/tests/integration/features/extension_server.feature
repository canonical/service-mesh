Feature: Extension server relation
  The envoy-ai-controller-k8s charm is the provider of the envoy-extension-server
  relation. It advertises its Extension Server gRPC endpoint to an Envoy Gateway
  control plane (the envoy-controller-k8s charm) and reads that control plane's
  identity back from the requirer.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates

  Scenario: Charm blocks until the extension-server relation is established
    Then the charm is blocked with message "Missing relation: envoy-extension-server"

  Scenario: Extension server endpoint is published to the controller
    When the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status
    Then the envoy-extension-server relation data contains the extension server fqdn
    And the envoy-extension-server relation data contains the extension server port

  Scenario: Controller identity is received from the extension-server requirer
    When the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status
    Then the envoy-extension-server relation data contains the controller name
    And the envoy-extension-server relation data contains the controller namespace
