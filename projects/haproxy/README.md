# HAProxy → ingress-configurator → Istio ingress

A small experiment: put the machine **HAProxy** charm in front of the k8s **Istio ingress
gateway**, wiring them together through the **ingress-configurator** charm over the
`haproxy-route-tcp` relation. HAProxy acts as an L4 (TCP) entry point; Istio does the real L7 work.

## Topology

```
client ──tcp/tls──> haproxy (machine, LXD) ──tcp──> istio-ingress LB :80/:443 ──> istio-envoy ──> app
                        ▲
        ingress-configurator (k8s) configures haproxy over `haproxy-route-tcp`
        and points its TCP backend at the istio-ingress LoadBalancer IP.
```

- `istio-k8s`, `istio-ingress-k8s`, `ingress-configurator`, BookInfo → **k8s** model (`mcrk8s:mesh`).
- `haproxy` → **machine** model (`lxd:proxy`); it's a machine charm, so it needs an LXD controller.
- The `haproxy-route-tcp` relation is a **cross-model / cross-controller** relation (`juju offer` + `consume`).
- "Pointing at Istio" is **config**, not a relation: ingress-configurator's `tcp-backend-addresses`
  + `tcp-port-mapping` are set to the istio-ingress LB IP and ports (integrator / config-driven mode).

## What we validated

**1. Plain TCP passthrough (HTTP).** haproxy forwards raw TCP on `:80` to the istio LB `:80`.
All routing (`/mesh-bookinfo-productpage-k8s`) is done by istio-envoy. `curl` through haproxy → **200**.

**2. TLS passthrough (HTTPS, SNI-routed).** With self-signed-certificates on istio-ingress,
the gateway serves HTTPS `:443` for `bookinfo.test`. ingress-configurator is set to
`tcp-tls-terminate=false` + `tcp-hostname=bookinfo.test`, which renders in haproxy as:

```
frontend haproxy_route_tcp_443
    mode tcp
    tcp-request content accept if { req_ssl_hello_type 1 }   # wait for TLS ClientHello
    acl ... req.ssl_sni -i bookinfo.test                     # match SNI (cleartext)
    use_backend ... 192.168.0.132:443                        # forward ciphertext, no decrypt
```

`curl https://bookinfo.test/... ` through haproxy → **200**, and the served cert is
`CN=bookinfo.test` issued by the SSC CA — i.e. **istio's** cert. HAProxy never terminates TLS;
it only reads the SNI to route. Istio holds the key and does everything else.

## Key takeaways

- In these modes HAProxy is a **dumb L4 box**: TCP forward, optionally matching the ClientHello SNI.
  No decryption, no HTTP parsing, no host/path routing — Istio owns all of that.
- The hostname lives in **two** places that must match: `istio-ingress-k8s external_hostname`
  (cert SAN + L7 routing) and `ingress-configurator tcp-hostname` (haproxy's SNI match, pushed via
  the relation). It is **not** HAProxy's own config.
- SSC on the **haproxy** side is unused for passthrough (the client trusts istio's cert); it would
  only matter with `tcp-tls-terminate=true` (haproxy terminates and re-encrypts).

## Gotchas

- Use **`haproxy 2.8/candidate`**. `2.8/stable` ships `haproxy_route_tcp` v1.3 (requires `port`,
  no `port_mapping`) and rejects the requirer databag; `2.8/edge` is arm64-only.
- `juju info haproxy` shows stale classic-charm relation metadata — trust the charm source.
- For a plain-HTTP pass haproxy needs `external-hostname` set and TCP TLS disabled, or it blocks
  on "TLS not ready".

## Reproduce

Prereqs: `lxd` and `mcrk8s` (MetalLB-enabled) controllers bootstrapped; `just` + `jq` installed.

```bash
just -f setup.just all               # models, deploy, relate, configure, verify (HTTP passthrough)
just -f setup.just bookinfo          # optional real backend behind istio
just -f setup.just verify-bookinfo   # HTTP 200 through haproxy
just -f setup.just tls-passthrough   # SSC + SNI passthrough on :443, then verify (HTTPS 200)
just -f setup.just clean             # tear down
```

See `setup.just` for the individual recipes and tunables (controller/model names, channels, ports).
