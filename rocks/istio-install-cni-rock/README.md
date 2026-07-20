# istio-install-cni-rock

[![Open a PR to OCI Factory](https://github.com/canonical/istio-install-cni-rock/actions/workflows/release-oci-factory.yaml/badge.svg)](https://github.com/canonical/istio-install-cni-rock/actions/workflows/release-oci-factory.yaml)
[![Publish to GHCR:dev](https://github.com/canonical/istio-install-cni-rock/actions/workflows/release-dev.yaml/badge.svg)](https://github.com/canonical/istio-install-cni-rock/actions/workflows/release-dev.yaml)
[![Update rock](https://github.com/canonical/istio-install-cni-rock/actions/workflows/update.yaml/badge.svg)](https://github.com/canonical/istio-install-cni-rock/actions/workflows/update.yaml)

A [rock](https://canonical-rockcraft.readthedocs-hosted.com/en/latest/) for [Istio's](https://istio.io/) [install-cni](https://hub.docker.com/r/istio/install-cni) image, which is defined [here](https://github.com/istio/istio/blob/master/cni/deployments/kubernetes/Dockerfile.install-cni).  This image is for installing Istio's CNI plugin, which is used for Istio's ambient mesh, and is described more [here](https://github.com/istio/istio/tree/master/cni#overview).

This repository holds all the necessary files to build a rock for the upstream versions we support. The rock is used indirectly by the [istio-k8s-operator](https://github.com/canonical/istio-k8s-operator/) charm.

The rocks on this repository are built with [OCI Factory](https://github.com/canonical/oci-factory/), which also takes care of periodically rebuilding the images.

Automation takes care of:
* validating PRs, by simply trying to build the rock;
* pulling upstream releases, creating a PR with the necessary files to be manually reviewed;
* releasing to GHCR at [ghcr.io/canonical/istio-install-cni:dev](https://ghcr.io/canonical/istio-install-cni:dev), when merging to main, for development purposes.
