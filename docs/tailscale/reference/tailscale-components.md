---
myst:
  html_meta:
    description: "Browse the reference for the charms and snaps that make up Charmed Tailscale, including component roles, workload versions and source locations."
---

# Tailscale components

This page describes the charms and snaps that make up Charmed Tailscale.

## Tailscale charms

| Charm                                                                                           | Substrate | Workload version | Track | Contributing                                                                                                                                          |
| ----------------------------------------------------------------------------------------------- | --------- | ---------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Tailscale K8s Operator](https://charmhub.io/tailscale-k8s)                                     | K8s       | 1.102            | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/tailscale-k8s), [issues](https://github.com/canonical/service-mesh/issues)        |
| [Tailscale Beacon](https://charmhub.io/tailscale-beacon-k8s)                                    | K8s       | -                | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/tailscale-beacon-k8s), [issues](https://github.com/canonical/service-mesh/issues) |
| [Tailscale Beacon](https://charmhub.io/tailscale-beacon)                                        | Machines  | 1                | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/tailscale-beacon), [issues](https://github.com/canonical/service-mesh/issues)     |
| [Tailscale Config](https://github.com/canonical/service-mesh/tree/main/charms/tailscale-config) | Any       | -                | dev   | [Source](https://github.com/canonical/service-mesh/tree/main/charms/tailscale-config), [issues](https://github.com/canonical/service-mesh/issues)     |

## Tailscale snaps

| Snap                                        | Used by                                                  | Contributing                                                                                                        |
| ------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| [Tailscale](https://snapcraft.io/tailscale) | [Tailscale Beacon](https://charmhub.io/tailscale-beacon) | [Source](https://github.com/canonical/tailscale-snap), [issues](https://github.com/canonical/tailscale-snap/issues) |
