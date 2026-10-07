---
myst:
  html_meta:
    description: "Browse the reference for the charms and rocks that make up Charmed Istio ambient, including component roles, workload versions and source locations."
---

# Istio components

This page describes the charms and rocks that make up Charmed Istio ambient.

## Istio charms

| Charm                                                  | Substrate | Workload version | Track | Contributing                                                                                                                                       |
| ------------------------------------------------------ | --------- | ---------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Istio](https://charmhub.io/istio-k8s)                 | K8s       | 1.31             | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/istio-k8s), [issues](https://github.com/canonical/service-mesh/issues)         |
| [Istio Beacon](https://charmhub.io/istio-beacon-k8s)   | K8s       | -                | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/istio-beacon-k8s), [issues](https://github.com/canonical/service-mesh/issues)  |
| [Istio Ingress](https://charmhub.io/istio-ingress-k8s) | K8s       | -                | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/istio-ingress-k8s), [issues](https://github.com/canonical/service-mesh/issues) |
| [Kiali](https://charmhub.io/kiali-k8s)                 | K8s       | 2.3              | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/kiali-k8s), [issues](https://github.com/canonical/service-mesh/issues)         |

### Test charms

| Charm                                                                | Substrate | Workload version | Track | Contributing                                                                                                                                              |
| -------------------------------------------------------------------- | --------- | ---------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Bookinfo Details](https://charmhub.io/bookinfo-details-k8s)         | K8s       | 1.20             | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/bookinfo-details-k8s), [issues](https://github.com/canonical/service-mesh/issues)     |
| [Bookinfo Productpage](https://charmhub.io/bookinfo-productpage-k8s) | K8s       | 1.20             | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/bookinfo-productpage-k8s), [issues](https://github.com/canonical/service-mesh/issues) |

## Istio rocks

| Rock                                                                            | Used by                                | Contributing                                                                                                                                           |
| ------------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`ubuntu/istio-pilot`](https://hub.docker.com/r/ubuntu/istio-pilot)             | [Istio](https://charmhub.io/istio-k8s) | [Source](https://github.com/canonical/service-mesh/tree/main/rocks/istio-pilot-rock), [issues](https://github.com/canonical/service-mesh/issues)       |
| [`ubuntu/istio-ztunnel`](https://hub.docker.com/r/ubuntu/istio-ztunnel)         | [Istio](https://charmhub.io/istio-k8s) | [Source](https://github.com/canonical/service-mesh/tree/main/rocks/istio-ztunnel-rock), [issues](https://github.com/canonical/service-mesh/issues)     |
| [`ubuntu/istio-install-cni`](https://hub.docker.com/r/ubuntu/istio-install-cni) | [Istio](https://charmhub.io/istio-k8s) | [Source](https://github.com/canonical/service-mesh/tree/main/rocks/istio-install-cni-rock), [issues](https://github.com/canonical/service-mesh/issues) |
| [`ubuntu/kiali`](https://hub.docker.com/r/ubuntu/kiali)                         | [Kiali](https://charmhub.io/kiali-k8s) | [Source](https://github.com/canonical/service-mesh/tree/main/rocks/kiali-rock), [issues](https://github.com/canonical/service-mesh/issues)             |
