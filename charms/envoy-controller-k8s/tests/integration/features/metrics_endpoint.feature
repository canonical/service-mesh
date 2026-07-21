Feature: Prometheus metrics-endpoint relation
  The envoy-controller-k8s charm publishes its :19001/metrics endpoint over
  the metrics-endpoint relation so an OTelCol (or Prometheus) can scrape
  controller-runtime, workqueue, admission-webhook and certwatcher metrics
  that Envoy Gateway does not OTLP-export natively.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust
    And the charm reaches active status

  Scenario: metrics-endpoint publishes the controller scrape target
    Given the opentelemetry-collector charm is deployed
    When the metrics-endpoint relation is established with opentelemetry-collector
    Then the metrics-endpoint relation data advertises the controller port
    And the metrics-endpoint relation data ships alert rules
