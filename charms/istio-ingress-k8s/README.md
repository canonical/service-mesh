# istio-ingress-k8s


[![CharmHub Badge](https://charmhub.io/istio-ingress-k8s/badge.svg)](https://charmhub.io/istio-ingress-k8s)
[![Release](https://github.com/canonical/istio-ingress-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/istio-ingress-k8s-operator/actions/workflows/release.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

## Description

[Istio](https://istio.io) is an open source project that implements a service mesh, allowing for a way to observe and control the traffic flow between applications in Kubernetes. Istio is a key tool in securing Kubernetes workloads and hardening your environment.

This [Juju](https://juju.is) charmed operator, written with the [Operator Lifecycle Manager Framework](https://juju.is/docs/olm), powers _ingress controller-like_ capabilities on Kubernetes. By _ingress controller-like_ capabilities, we mean that the istio-ingress Kubernetes charmed operator exposes Juju applications to the outside of a Kubernetes cluster or a service mesh, **without** relying on the [`ingress` resource](https://kubernetes.io/docs/concepts/services-networking/ingress/) of Kubernetes.

Instead, istio-ingress is instructed to expose Juju applications through relations with them and **utilizes the new** [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/). The operator is designed to be used in conjunction with [istio-core-k8s](https://github.com/canonical/istio-core-k8s-operator) to deploy and configure Istio using Juju.


More information: https://charmhub.io/istio-ingress-k8s

## Usage

**todo**