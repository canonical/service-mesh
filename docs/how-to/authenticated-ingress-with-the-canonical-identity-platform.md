# Authenticated Ingress with the Canonical Identity Platform

## Requirements

* A [microk8s cluster cluster](https://canonical.com/microk8s/docs/getting-started#1-overview)

> **Note**
> This tutorial requires you to have 2 IP addresses available to your k8s cluster. One for the traefik deployed with the identity bundle and one for istio-ingress-k8s. This can be done by enabling metallb with an IP range. For example:
> `microk8s enable metallb:192.168.0.XXX-192.168.0.YYY`

* A [bootstrapped juju controller](https://documentation.ubuntu.com/juju/3.6/tutorial/)
* [Terraform](https://snapcraft.io/terraform) (For the identity tutorial)

For a smoother run, make sure your cluster has enough resources (at least 4 vCPU and 8 GB RAM is recommended), and that DNS and load balancer support are enabled in your Kubernetes environment.

## Setup the prerequisites

* Deploy the [Canonical Identity Platform](https://canonical-identity.readthedocs-hosted.com/tutorial/canonical-identity-platform/)

> **Note**
> If you see hydra and kratos in blocked state with "Missing integration pg-database", run the following:
> ```bash
> juju switch iam
> juju integrate hydra postgresql
> juju integrate kratos postgresql
> ```

> **Note**
> If you do not want to bother with 2 factor authentication for the tutorial, you can run:
> ```bash
> juju config kratos enforce_mfa=false
> ```

* `juju add-model istio-system`
* `juju deploy istio-k8s istio --trust --channel dev/edge`
* `juju offer istio:istio-ingress-config ingress-config`
* Wait for istio to reach active/idle

## Deploy Authenticated Bookinfo

### Deploy the Charms

* `juju add-model bookinfo`
* `juju deploy oauth2-proxy-k8s oauth2`
* `juju config oauth2 dev=true`
* `juju deploy istio-ingress-k8s ingress --trust --channel dev/edge`
* `juju deploy bookinfo-productpage-k8s bookinfo`
* `juju deploy bookinfo-details-k8s bookinfo-details`

### Consume Cross-Model Integrations

* `juju consume iam.oauth-offer`
* `juju consume istio-system.ingress-config`
* `juju consume core.send-ca-cert`
* `juju consume core.certificates`

### Integrate your charms

* `juju integrate bookinfo:details bookinfo-details:details`
* `juju integrate bookinfo:ingress ingress:ingress`
* `juju integrate oauth2 oauth-offer`
* `juju integrate oauth2:forward-auth ingress:forward-auth`
* `juju integrate oauth2:receive-ca-cert send-ca-cert`
* `juju integrate ingress ingress-config`
* `juju integrate ingress:certificates certificates`
* `juju integrate oauth2:ingress ingress:ingress-unauthenticated`
* Wait for all charms to reach active/idle

### Test your deployment

* Navigate to `http://<ingress-address>/bookinfo-bookinfo` in your browser. You should be prompted to log in.
* Log in and access the bookinfo page!
