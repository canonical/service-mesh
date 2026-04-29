# Authenticated Ingress with the Canonical Identity Platform

## Introduction

In this tutorial, you will learn how to set up authentication for any application using Istio and the Canonical Identity Platform. We will deploy the sample "bookinfo" application and configure Istio to redirect unauthenticated traffic to oauth2-proxy.

## Requirements

* A [MicroK8s cluster](https://canonical.com/microk8s/docs/getting-started)

```{note}
This tutorial requires you to have 2 IP addresses available to your k8s cluster. One for the traefik instance deployed with the identity bundle and one for istio-ingress-k8s. This can be done by enabling metallb with an IP range. For example:
`microk8s enable metallb:192.168.0.XXX-192.168.0.YYY`
See [the docs](https://canonical.com/microk8s/docs/addon-metallb) for more info.
```

* A [bootstrapped juju controller](https://documentation.ubuntu.com/juju/3.6/tutorial/)
* [Terraform](https://snapcraft.io/terraform) (For the identity tutorial)

## Set up the prerequisites

* First follow the tutorial to deploy the [Canonical Identity Platform](https://canonical-identity.readthedocs-hosted.com/tutorial/canonical-identity-platform/). This is what will be used to manage users and authentication.

````{note}
If you see hydra and kratos in blocked state with "Missing integration pg-database", run the following:
```{bash}
juju switch iam
juju integrate hydra postgresql
juju integrate kratos postgresql
```
````

````{note}
If you do not want to bother with 2 factor authentication for the tutorial, you can run:
```{bash}
juju config kratos enforce_mfa=false
```
````

* Next we deploy istio to the cluster, enabling it to manage network traffic.
  ```{bash}
  juju add-model istio-system
  juju deploy istio-k8s istio --trust --channel dev/edge
  juju offer istio:istio-ingress-config ingress-config
  ```
  Then Wait for istio to reach active/idle.

```{note}
We need to use the `dev` track for the Istio charms currently as the 2 track has an old Istio version.
Any release track newer than 2 should work just fine.
```

## Deploy Authenticated Bookinfo

* Deploy the bookinfo application
  ```{bash}
  juju add-model bookinfo
  juju deploy bookinfo-productpage-k8s bookinfo
  juju deploy bookinfo-details-k8s bookinfo-details
  juju integrate bookinfo:details bookinfo-details:details
  ```
* Deploy oauth2-proxy and integrate it with the Identity Platform
  ```{bash}
  juju deploy oauth2-proxy-k8s oauth2
  juju config oauth2 dev=true  # dev=true is required since the certificates we will be using are self-signed.
  juju consume core.send-ca-cert
  juju integrate oauth2:receive-ca-cert send-ca-cert
  juju consume iam.oauth-offer
  juju integrate oauth2 oauth-offer
  ```
* Deploy istio-ingress and use it to route traffic to bookinfo and oauth2-proxy
  ```{bash}
  juju deploy istio-ingress-k8s ingress --trust --channel dev/edge
  juju consume core.certificates
  juju integrate ingress:certificates certificates
  juju integrate bookinfo:ingress ingress:ingress
  juju integrate oauth2:ingress ingress:ingress-unauthenticated
  ```
At this point, after waiting for everything to settle, you should be able to run `juju run bookinfo/leader get-url` and it should return an https url. If you navigate to the returned url in your browser, you should reach the bookinfo app.

* Enable authentication
  ```{bash}
  juju integrate oauth2:forward-auth ingress:forward-auth
  juju consume istio-system.ingress-config
  juju integrate ingress ingress-config
  ```
Wait for all charms to reach active/idle

### Test your deployment

* Run `juju run bookinfo/leader get-url` and navigate to the returned URL in your browser. You should be prompted to log in. Log in and access the bookinfo page!
