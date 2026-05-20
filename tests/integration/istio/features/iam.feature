Feature: Authenticated ingress with the Canonical Identity Platform

  Background:
    Given a juju model with istio-k8s deployed
    And istio-k8s offers istio-ingress-config
    And the Canonical Identity Platform is deployed
    And a juju model for bookinfo services

  Scenario: Bookinfo with authenticated ingress can be deployed successfully
    When you deploy bookinfo
    And you add an istio-ingress with oauth2-proxy
    And you integrate this model with iam
    And you integrate the ingress with istio
    Then all charms are active

  Scenario: Unauthenticated requests are redirected to login
    Given bookinfo is deployed with authenticated ingress
    When external client requests GET /productpage on the ingress gateway
    Then the request is redirected to the login page
