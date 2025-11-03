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

## Using Istio with Cilium CNI

`Cilium` is an `eBPF` based CNI which includes some intelligent kernel level traffic re-routing using `BPF` programs. This traffic re-routing can potentially interfere with Istios mesh features.

```{note}
The complete compatibility documentation between Cilium and Istio can be found [here](https://docs.cilium.io/en/stable/network/servicemesh/istio/). This documentation only covers certain gotcha's that is not explicitly clear from the mentioned doc.
```

By default `Cilium` is designed to be the exclusive CNI which wont allow the Istio CNI plugin to be succefully deployed. Hence it is important to make sure `Cilium` is configured to allow external CNI plugins.

Assuming `Cilium` allows `Istio's` CNI plugin, the compatibility, the major compatibility issue between them is caused by the fact that `Cilium` uses BPF programs to load balance traffic at the kernel level. This means traffic directed at Kubernetes Services are re-routed by Cilium directly to the destination Pod. 

`Istio`, in order to apply policies and encrypt traffic, routes the traffic via its `ztunnel` component either using `iptables` or higher level `BPF` programs. Since the `Cilium's` re-routing applies at the kernel level, the traffic is never routed through the `ztunnel` at the source. This prevents `Istio` from successfully encrypting the traffic or applying the `AuthorizationPolicies`. This issue can be solved by the `socketLB.hostNamespaceOnly: true` setting in `Cilium` which basically instructs `Cilium` to limit load balancing to the host host network namespace. Hence the K8s internal traffic flows through the normal network stack allowing `Istio` to function normally.

An important gotcha that is not mentioned in the `Cilium` documentation is the fact that, even when `socketLB.hostNamespaceOnly` is set to be `false`, the destination `ztunnel` will successfully capture the traffic to the destination pod and might apply L4 policies directed at the pod. This might give the impression that service mesh is working successfully and will mask the fact the traffic between the source pod and destination pod is not encrypted by Istio (if `mTLS` mode is set to be `PERMISSIVE`).

The recommended configuration To successfully use Charmed Istio with Canonical Kubernetes can be found in [this](../how-to/use-charmed-istio-with-canonical-kubernetes.md) how-to documentation.
