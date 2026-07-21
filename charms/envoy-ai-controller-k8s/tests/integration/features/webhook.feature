Feature: ExtProc sidecar-injection webhook
  The envoy-ai-controller-k8s charm manages the ExtProc sidecar-injector
  MutatingWebhookConfiguration and patches it with the CA from the
  tls-certificates relation.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: ExtProc webhook is created
    Then a MutatingWebhookConfiguration for ExtProc sidecar injection exists
    And the ExtProc webhook targets the pod-mutation path on the webhook port
    And the ExtProc webhook selects only envoy-gateway managed pods

  Scenario: ExtProc webhook caBundle is populated from the certificates relation
    Then the ExtProc webhook caBundle is populated
