Feature: Gateway resources
  The envoy-ingress-k8s charm creates GatewayClass and Gateway
  resources and verifies the controller accepts them.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust and active
    And the envoy-ingress-k8s charm is deployed with trust and active

  Scenario: GatewayClass is created and accepted
    Then a GatewayClass with controllerName "gateway.envoyproxy.io/gatewayclass-controller" exists
    And the GatewayClass has an Accepted condition set to True

  Scenario: Gateway is created and programmed
    Then a Gateway resource exists in the charm's namespace
    And the Gateway has a Programmed condition set to True

  Scenario: Envoy Proxy pod is provisioned
    Then an Envoy Proxy pod is running in the Gateway's namespace
