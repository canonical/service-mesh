---
myst:
  html_meta:
    description: "Browse the reference for the charms and OCI images that make up Charmed Envoy, including component roles, workload versions and source locations."
---

# Envoy components

This page describes the charms and OCI images that make up Charmed Envoy.

## Envoy charms

| Charm                                                                      | Substrate | Workload version | Track | Contributing                                                                                                                                             |
| -------------------------------------------------------------------------- | --------- | ---------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Envoy Gateway Controller](https://charmhub.io/envoy-controller-k8s)       | K8s       | 1.7              | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/envoy-controller-k8s), [issues](https://github.com/canonical/service-mesh/issues)    |
| [Envoy Gateway Ingress](https://charmhub.io/envoy-ingress-k8s)             | K8s       | -                | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/envoy-ingress-k8s), [issues](https://github.com/canonical/service-mesh/issues)       |
| [Envoy AI Gateway Controller](https://charmhub.io/envoy-ai-controller-k8s) | K8s       | 0.6              | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/envoy-ai-controller-k8s), [issues](https://github.com/canonical/service-mesh/issues) |

## OCI images

The Envoy charms use upstream OCI images from Docker Hub.

| Image                                                                                           | Used by                                                                              | Contributing                                                                                                  |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| [`envoyproxy/gateway`](https://hub.docker.com/r/envoyproxy/gateway)                             | [Envoy Gateway Controller](https://charmhub.io/envoy-controller-k8s)                 | [Source](https://github.com/envoyproxy/gateway), [issues](https://github.com/envoyproxy/gateway/issues)       |
| [`envoyproxy/ai-gateway-controller`](https://hub.docker.com/r/envoyproxy/ai-gateway-controller) | [Envoy AI Gateway Controller](https://charmhub.io/envoy-ai-controller-k8s)           | [Source](https://github.com/envoyproxy/ai-gateway), [issues](https://github.com/envoyproxy/ai-gateway/issues) |
| [`envoyproxy/ai-gateway-extproc`](https://hub.docker.com/r/envoyproxy/ai-gateway-extproc)       | [Envoy AI Gateway Controller](https://charmhub.io/envoy-ai-controller-k8s) (dynamic) | [Source](https://github.com/envoyproxy/ai-gateway), [issues](https://github.com/envoyproxy/ai-gateway/issues) |
