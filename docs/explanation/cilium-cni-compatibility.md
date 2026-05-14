# Compatibility with Cilium CNI

`Cilium` is an `eBPF` based CNI which includes some intelligent kernel level traffic re-routing using `eBPF` programs. This traffic re-routing can potentially interfere with `Istio ambient's` mesh features.

```{note}
The complete compatibility documentation between Cilium and Istio can be found [here](https://docs.cilium.io/en/stable/network/servicemesh/istio/). This documentation only covers certain gotchas that is not explicitly clear from the mentioned doc.
```

By default `Cilium` is designed to be the exclusive CNI which wont allow the Istio CNI plugin to be successfully deployed. Hence it is important to make sure `Cilium` is configured to allow external CNI plugins.

Assuming `Cilium` allows `Istio's` CNI plugin, the major compatibility issue between them is caused by the fact that `Cilium` load balances traffic at the kernel level. This means traffic directed at Kubernetes Services are re-routed by Cilium directly to the destination Pod.

`Istio ambient`, in order to apply policies and encrypt traffic, routes the traffic via its `ztunnel` component either using `iptables` or higher level `eBPF` programs. Since the `Cilium's` re-routing applies at the kernel level, the traffic is never routed through the `ztunnel` at the source. This prevents `Istio ambient` from successfully encrypting the traffic or applying the `AuthorizationPolicies`. This issue can be solved by the `socketLB.hostNamespaceOnly: true` setting in `Cilium` which basically instructs `Cilium` to limit load balancing to the host network namespace. Hence the K8s internal traffic flows through the normal network stack allowing `Istio ambient` to function normally.

An important gotcha that is not mentioned in the `Cilium` documentation is the fact that, even when `socketLB.hostNamespaceOnly` is set to be `false`, the destination `ztunnel` will successfully capture the traffic to the destination pod and might apply L4 policies directed at the pod. This might give the impression that service mesh is working successfully and will mask the fact the traffic between the source pod and destination pod is not encrypted by Istio ambient (if `mTLS` mode is set to be `PERMISSIVE`).

The recommended configuration to successfully use Charmed Istio with Canonical Kubernetes with the `Cilium` CNI can be found in [this](../how-to/use-charmed-istio-with-canonical-kubernetes.md) how-to documentation.
