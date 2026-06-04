Feature: CRD management
  The envoy-controller-k8s charm installs and manages Gateway API,
  Gateway Inference Extension, and AI Gateway CRDs.

  Background:
    Given a Juju Kubernetes model
    And the self-signed-certificates charm is deployed
    And the envoy-controller-k8s charm is deployed with trust
    And the certificates relation is established with self-signed-certificates
    And the charm reaches active status

  Scenario: Gateway API CRDs are installed
    Then the following CRDs exist on the cluster:
      | crd                                              |
      | gatewayclasses.gateway.networking.k8s.io          |
      | gateways.gateway.networking.k8s.io                |
      | httproutes.gateway.networking.k8s.io              |
      | grpcroutes.gateway.networking.k8s.io              |
      | referencegrants.gateway.networking.k8s.io         |

  Scenario: Gateway Inference Extension CRDs are installed
    Then the following CRDs exist on the cluster:
      | crd                                              |
      | inferencepools.inference.networking.k8s.io        |

  Scenario: AI Gateway CRDs are absent by default
    Then the following CRDs do not exist on the cluster:
      | crd                                              |
      | aigatewayroutes.aigateway.envoyproxy.io           |
      | aiservicebackends.aigateway.envoyproxy.io         |
      | backendsecuritypolicies.aigateway.envoyproxy.io   |
      | mcproutes.aigateway.envoyproxy.io                 |
      | gatewayconfigs.aigateway.envoyproxy.io            |

  Scenario: AI Gateway CRDs are installed when enabled
    When the charm config enable-ai-gateway is set to "true"
    And the charm reaches active status
    Then the following CRDs exist on the cluster:
      | crd                                              |
      | aigatewayroutes.aigateway.envoyproxy.io           |
      | aiservicebackends.aigateway.envoyproxy.io         |
      | backendsecuritypolicies.aigateway.envoyproxy.io   |
      | mcproutes.aigateway.envoyproxy.io                 |
      | gatewayconfigs.aigateway.envoyproxy.io            |

  Scenario: AI Gateway CRDs are removed when disabled
    Given the charm config enable-ai-gateway is set to "true"
    And the charm reaches active status
    When the charm config enable-ai-gateway is set to "false"
    And the charm reaches active status
    Then the following CRDs exist on the cluster:
      | crd                                              |
      | inferencepools.inference.networking.k8s.io        |
    And the following CRDs do not exist on the cluster:
      | crd                                              |
      | aigatewayroutes.aigateway.envoyproxy.io           |
      | aiservicebackends.aigateway.envoyproxy.io         |
      | backendsecuritypolicies.aigateway.envoyproxy.io   |
      | mcproutes.aigateway.envoyproxy.io                 |
      | gatewayconfigs.aigateway.envoyproxy.io            |

