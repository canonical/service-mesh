Feature: AI Gateway CRDs
  The envoy-ai-controller-k8s charm installs the aigateway.envoyproxy.io CRDs
  when it reconciles the Envoy AI Gateway control plane.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: AI Gateway CRDs exist on the cluster
    Then the AI Gateway CRDs exist on the cluster

  Scenario: Each installed AI Gateway CRD is present
    Then the following CRDs exist on the cluster:
      | name                                             |
      | aigatewayroutes.aigateway.envoyproxy.io          |
      | aiservicebackends.aigateway.envoyproxy.io        |
      | backendsecuritypolicies.aigateway.envoyproxy.io  |
      | gatewayconfigs.aigateway.envoyproxy.io           |
      | mcproutes.aigateway.envoyproxy.io                |
      | quotapolicies.aigateway.envoyproxy.io            |
