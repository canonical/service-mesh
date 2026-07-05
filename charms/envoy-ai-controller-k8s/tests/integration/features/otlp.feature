Feature: OTLP relation
  The envoy-ai-controller-k8s charm switches on OTLP metrics export in the
  ExtProc sidecars it injects by passing the collector endpoint to the
  controller as an extra ExtProc environment variable.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed
    And the envoy-ai-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the envoy-extension-server relation is established with envoy-controller-k8s
    And the charm reaches active status

  Scenario: Charm remains active without OTLP relation
    Then the charm is active
    And the controller command carries no ExtProc OTLP environment

  Scenario: ExtProc OTLP export is configured when relation is established
    Given the opentelemetry-collector charm is deployed
    When the otlp relation is established with opentelemetry-collector
    And the charm reaches active status
    Then the controller command sets the ExtProc OTLP metrics endpoint
    And the ExtProc OTLP metrics endpoint matches the OTLP relation data

  Scenario: Alert rules are published when relation is established
    Given the opentelemetry-collector charm is deployed
    When the otlp relation is established with opentelemetry-collector
    And the charm reaches active status
    Then the otlp relation data contains alert rules

  Scenario: ExtProc OTLP export is removed when relation is broken
    Given the otlp relation is established with opentelemetry-collector
    And the charm reaches active status
    When the otlp relation is removed
    And the charm reaches active status
    Then the controller command carries no ExtProc OTLP environment
