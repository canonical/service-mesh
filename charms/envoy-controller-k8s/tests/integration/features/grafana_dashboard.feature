Feature: Grafana dashboard relation
  The envoy-controller-k8s charm ships Grafana dashboard JSON
  definitions when related to Grafana.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust
    And the charm reaches active status

  Scenario: Dashboard data is provided when relation is established
    Given the grafana-k8s charm is deployed
    When the grafana-dashboard relation is established with grafana-k8s
    And the charm reaches active status
    Then the grafana-dashboard relation data contains dashboard JSON
    And the dashboard JSON includes a controller health dashboard
    And the dashboard JSON includes a data plane metrics dashboard
