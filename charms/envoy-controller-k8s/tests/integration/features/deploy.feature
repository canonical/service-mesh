Feature: Charm deployment
  The envoy-controller-k8s charm deploys and reaches active status.
  It mints its own control-plane certificates via Envoy Gateway's certgen,
  so no certificates relation is required.

  Background:
    Given a Juju Kubernetes model

  Scenario: Charm deploys and reaches active status
    When the envoy-controller-k8s charm is deployed with trust
    Then the charm reaches active status

  Scenario: Charm blocks without trust
    When the envoy-controller-k8s charm is deployed without trust
    Then the charm is blocked with message "Trust not granted. Run 'juju trust envoy-controller-k8s'"
