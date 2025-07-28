# Istio

[Istio](https://istio.io) is an implementation of a [service mesh](./service-mesh.md).  It helps you:

* ensure all microservices in an application [communicate via TLS](https://istio.io/latest/docs/concepts/security/#mutual-tls-authentication) **without modifying the application**
* implement fine-grained [authorization controls](https://istio.io/latest/docs/concepts/security/#mutual-tls-authentication) to control exactly which microservices can talk to each other, for example blocking all incoming traffic to `MyApp-backend` except `GET` requests coming from `MyApp-frontend`
* gain visibility into the traffic flow of your microservice application via [automated telemetry collection](https://istio.io/latest/docs/concepts/observability/)

Although Kubernetes natively provides facilities to do some of this, Istio implements richer solutions.  For example, Istio's [AuthorizationPolicy](https://istio.io/latest/docs/reference/config/security/authorization-policy/) object implements fine-grained authorization controls, and Istio can automate mutual TLS between all applications on the mesh.

## Charmed Istio

Charmed Istio is an opinionated deployment of Istio using [Juju](http://juju.is/).  The goals of Charmed Istio are to:

* provide a simple-to-deploy, easy-to-manage Istio experience, giving most of Istio's benefits without a need for advanced Istio experience
* be customizable for power users, so users can build advanced use cases on top of the standard Charmed Istio base

Charmed Istio uses Istio's [Ambient Mode](https://istio.io/latest/docs/ambient/overview/) and is implemented through the following charms:

* [istio-k8s](https://charmhub.io/istio-k8s): for deploying and managing the Istio control panel, such as the Istio daemon and its resources
* [istio-beacon-k8s](https://charmhub.io/istio-beacon-k8s/): for integrating a Juju model and its applications to Charmed Istio, as well as deploying an Istio Waypoint for those applications
* [istio-ingress-k8s](https://charmhub.io/istio-ingress-k8s): for deploying and managing an Istio ingress gateway

Core elements of Charmed Istio include:

* automatic mTLS communication between all applications on the service mesh
* default security features through [hardened mode](./hardened-mode.md)
* easy, fine-grained, app-to-app authorization control through [managed mode](./managed-mode.md)
