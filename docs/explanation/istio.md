# Istio

[Istio](https://istio.io) is an implementation of a [service mesh](./service-mesh.md).  It helps you:

* ensure all microservices in my application [communicate via TLS](https://istio.io/latest/docs/concepts/security/#mutual-tls-authentication) **without modifying my application**
* implement fine-grained [authorization controls](https://istio.io/latest/docs/concepts/security/#mutual-tls-authentication) to control exactly which microservices can talk to each other, for example my blocking all incoming traffic to `MyApp-backend` except `GET` requests coming from `MyApp-frontend`
* gain visibility into the traffic flow of your microservice application via [automated telemetry collection](https://istio.io/latest/docs/concepts/observability/)

Although Kubernetes natively provides facilities to do some of this, Istio implements richer solutions.  For example, Istio's [AuthorizationPolicy](https://istio.io/latest/docs/reference/config/security/authorization-policy/) object lets you define: 

* which workloads can communicate with which
* specifically how they can communicate (what HTTP methods are allowed, endpoints can be accessed, etc)

which cannot be easily achieved using native Kubernetes features.

## Charmed Istio

Charmed Istio is an opinionated deployment of Istio using [Juju](http://juju.is/).  The goals of Charmed Istio are to:

* provide a simple-to-deploy, easy-to-manage Istio experience to most Juju users and use cases, giving most of Istio's benefits without a need for advanced Istio experience
* be customizable for power users, so users can build advanced use cases on top of the standard Charmed Istio base

Charmed Istio uses Istio's [Ambient Mode](https://istio.io/latest/docs/ambient/overview/) and is implemented through the following charms:

* [istio-k8s](https://charmhub.io/istio-k8s): for deploying and managing the Istio control panel, such as the Istio daemon and its resources
* [istio-beacon-k8s](https://charmhub.io/istio-beacon-k8s/): for integrating a Juju model and its applications to Charmed Istio, as well as deploying an Istio Waypoint for those applications
* [istio-ingress-k8s](https://charmhub.io/istio-ingress-k8s): for deploying and managing an Istio ingress gateway

Core elements of Charmed Istio include:

* automatic mTLS communication between all applications on the service mesh
* default security features through [hardened mode](./hardened-mode.md)
* easy [policy management](./managed-mode.md) and [fine-grained app-to-app authorization control]([managing traffic authorization for typical Charmed applications](../how-to/add-mesh-support-to-your-charm.md)) for typical Juju Charms use cases via the [`ServiceMeshConsumer`](https://charmhub.io/istio-beacon-k8s/libraries/service_mesh) charm library
