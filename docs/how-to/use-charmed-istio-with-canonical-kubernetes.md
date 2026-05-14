# Use Charmed Istio ambient with Canonical Kubernetes

[Canonical Kubernetes](https://documentation.ubuntu.com/canonical-kubernetes/latest/) out of the box uses [Cilium](https://cilium.io/use-cases/cni/) as its CNI provider. `Cilium` is a `eBPF` based CNI provider which also includes traffic redirection at the kernel level for efficiency. This traffic redirection can conflict with `Istio ambient's` workflow as explained [here](../explanation/istio.md).

For `Istio ambient` and `Cilium` to work together, some changes are required to the defaults with which the charmed istio and canonical Kubernetes are deployed.

## Configuring Canonical Kubernetes

```{note}
There is currently no documented way to configure Cilium using Canonical Kubernetes. But it can be done using one of the [recommended ways](https://docs.cilium.io/en/stable/configuration/index.html) by Cilium.
```

```{note}
This documentation only covers the configuration changes required from the default state of Canonical Kubernetes. If a custom Cilium configuration is used, please refer to this [Cilium documentation](https://docs.cilium.io/en/stable/network/servicemesh/istio/) for compatibility with Istio ambient.
```

The following requirements must be met for Canonical Kubernetes to work with Charmed Istio

- `socketLB.hostNamespaceOnly: true` (Helm) or `bpf-lb-sock-hostns-only: "true"` (Cilium CLI)

## Configuring Charmed Istio

For Charmed Istio to work together with Cilium (given Cilium has the recommended configuration), the `platform` configuration of the [`istio-k8s`](https://charmhub.io/istio-k8s/configurations) charm must be unset. This can, for example, be done using

```sh
juju config istio-k8s platform=""
```

Once Charmed Istio and Canonical Kubernetes are configured as recommended, the service-mesh capabilities of Istio ambient should function normally.
