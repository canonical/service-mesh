Feature: OTLP relation
  The envoy-controller-k8s charm configures Envoy Gateway's native
  OTLP metrics sink when related to an OTLP collector.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the charm reaches active status

  Scenario: Charm remains active without OTLP relation
    Then the charm is active
    And no OTLP sink is configured in the Envoy Gateway config
    And no OTLP sink is configured in the default EnvoyProxy resource

  Scenario: OTLP sink is configured when relation is established
    Given the opentelemetry-collector charm is deployed
    When the otlp relation is established with opentelemetry-collector
    And the charm reaches active status
    Then the Envoy Gateway config contains a telemetry.metrics.sinks entry
    And the default EnvoyProxy resource contains a telemetry.metrics.sinks entry
    And the sink type is OpenTelemetry
    And the sink host and port match the OTLP relation data
    And the default EnvoyProxy resource stamps Juju topology stats tags on proxy metrics

  Scenario: Alert rules are published when relation is established
    Given the opentelemetry-collector charm is deployed
    When the otlp relation is established with opentelemetry-collector
    And the charm reaches active status
    Then the otlp relation data contains alert rules

  Scenario: OTLP sink is removed when relation is broken
    Given the otlp relation is established with opentelemetry-collector
    And the charm reaches active status
    When the otlp relation is removed
    And the charm reaches active status
    Then no OTLP sink is configured in the Envoy Gateway config
    And no OTLP sink is configured in the default EnvoyProxy resource
