Feature: CRD management
  The envoy-controller-k8s charm installs and manages Gateway API,
  Envoy Gateway, and Gateway Inference Extension CRDs.

  Background:
    Given a Juju Kubernetes model
    And the envoy-controller-k8s charm is deployed with trust
    And the charm reaches active status

  Scenario: Gateway API CRDs are installed
    Then the following CRDs exist on the cluster:
      | crd                                              |
      | gatewayclasses.gateway.networking.k8s.io          |
      | gateways.gateway.networking.k8s.io                |
      | httproutes.gateway.networking.k8s.io              |
      | grpcroutes.gateway.networking.k8s.io              |
      | referencegrants.gateway.networking.k8s.io         |
      | backendtlspolicies.gateway.networking.k8s.io      |

  Scenario: Gateway Inference Extension CRDs are installed
    Then the following CRDs exist on the cluster:
      | crd                                                    |
      | inferencepools.inference.networking.k8s.io              |
      | inferencepools.inference.networking.x-k8s.io            |
      | inferenceobjectives.inference.networking.x-k8s.io       |
      | inferencepoolimports.inference.networking.x-k8s.io      |
      | inferencemodelrewrites.inference.networking.x-k8s.io    |

  Scenario: AI Gateway CRDs are not installed by this charm
    Then the following CRDs do not exist on the cluster:
      | crd                                              |
      | aigatewayroutes.aigateway.envoyproxy.io           |
      | aiservicebackends.aigateway.envoyproxy.io         |
      | backendsecuritypolicies.aigateway.envoyproxy.io   |
      | mcproutes.aigateway.envoyproxy.io                 |
      | gatewayconfigs.aigateway.envoyproxy.io            |
