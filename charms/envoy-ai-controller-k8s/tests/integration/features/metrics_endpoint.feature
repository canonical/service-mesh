Feature: Prometheus metrics-endpoint relation
  The envoy-ai-controller-k8s charm publishes its :8080/metrics endpoint over
  the metrics-endpoint relation so an OTelCol (or Prometheus) can scrape the
  controller-runtime metrics the controller does not OTLP-export natively.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: metrics-endpoint publishes the controller scrape target
    Given the opentelemetry-collector charm is deployed
    When the metrics-endpoint relation is established with opentelemetry-collector
    Then the metrics-endpoint relation data advertises the controller port
    And the metrics-endpoint relation data ships alert rules
