Feature: ExtProc sidecar injection into Envoy Gateway data-plane pods
  When an AIGatewayRoute targets a Gateway, the ExtProc admission webhook the
  envoy-ai-controller-k8s charm owns injects the ai-gateway-extproc container
  into the resulting Envoy Gateway data-plane pod, using the image reference
  the controller derives from the ai-gateway-image resource tag.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ingress-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: ExtProc sidecar is injected when an AIGatewayRoute references the Gateway
    Given an AIGatewayRoute references the ingress Gateway
    When the Envoy Gateway data-plane pod is recreated
    Then the data-plane pod runs the ai-gateway-extproc container
    And the ai-gateway-extproc image matches the ai-gateway-image tag under the upstream extproc repo
    And the data-plane pod is Ready
