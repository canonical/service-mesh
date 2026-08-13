# Reproduce: haproxy --(haproxy-route-tcp)--> ingress-configurator --> istio-ingress-k8s
#
# Prerequisites (assumed already done):
#   - An LXD (machine) controller is bootstrapped         -> `juju bootstrap localhost lxd`
#   - A MicroK8s (k8s) controller is bootstrapped w/ MetalLB enabled
#   - `just` and `jq` are installed
#
# Topology:
#   client -> haproxy (machine model, LXD) :80  --tcp-->  istio-ingress LB IP:80  -> istio-envoy
#   haproxy provides `haproxy-route-tcp`; ingress-configurator (k8s model) consumes it via CMR
#   and is configured (integrator/config-driven mode) to point its TCP backend at istio-ingress.

# --- configuration -----------------------------------------------------------

k8s_ctrl   := "mcrk8s"          # name of the k8s controller
lxd_ctrl   := "lxd"             # name of the lxd controller
mesh       := "mesh"            # k8s model (istio + configurator)
proxy      := "proxy"           # machine model (haproxy)

istio_channel  := "dev/edge"
ic_channel     := "latest/edge"
# NOTE: haproxy channel must ship haproxy_route_tcp >= v1.6 (port_mapping support).
# 2.8/stable (v1.3) is too old and rejects the databag; 2.8/edge is arm64-only.
haproxy_channel := "2.8/candidate"

frontend_port := "80"           # port exposed on haproxy
backend_port  := "80"           # istio-ingress gateway HTTP port

_mesh  := k8s_ctrl + ":" + mesh
_proxy := lxd_ctrl + ":" + proxy

# --- meta --------------------------------------------------------------------

default:
    @just --list

# Full run, end to end.
all: models deploy relate configure verify

# --- setup -------------------------------------------------------------------

models:
    juju add-model -c {{k8s_ctrl}} {{mesh}} || true
    juju add-model -c {{lxd_ctrl}} {{proxy}} || true

deploy: deploy-istio deploy-configurator deploy-haproxy

# Optional: a real backend behind istio-ingress so the chain returns 200 (not just 404).
# Deploys BookInfo (productpage + details) and routes it through istio-ingress `ingress`.
bookinfo:
    juju deploy -m {{_mesh}} bookinfo-productpage-k8s --channel latest/stable
    juju deploy -m {{_mesh}} bookinfo-details-k8s     --channel latest/stable
    juju integrate -m {{_mesh}} bookinfo-productpage-k8s:ingress istio-ingress-k8s:ingress
    juju integrate -m {{_mesh}} bookinfo-productpage-k8s:details bookinfo-details-k8s:details
    juju wait-for application -m {{_mesh}} bookinfo-productpage-k8s --query='status=="active"' --timeout=15m

# Curl the BookInfo productpage THROUGH haproxy (expects HTTP 200).
verify-bookinfo:
    #!/usr/bin/env bash
    set -euo pipefail
    HAP=$(just _haproxy-addr)
    PATH_=$(juju exec -m {{_mesh}} --unit bookinfo-productpage-k8s/0 -- bash -c \
      'for r in $(relation-ids ingress); do relation-get -r $r --app - istio-ingress-k8s; done' \
      | sed -n 's/.*"url": "[^/]*\/\/[^/]*\(\/[^"]*\)".*/\1/p')
    echo "productpage path: ${PATH_}"
    echo "== through haproxy (${HAP}${PATH_}/productpage) =="
    curl -s -o /dev/null -w "  http_code=%{http_code}\n" --max-time 10 "http://${HAP}${PATH_}/productpage"
    curl -s --max-time 10 "http://${HAP}${PATH_}/productpage" | grep -iE '<title>' | head -1


deploy-istio:
    juju deploy -m {{_mesh}} istio-k8s         --channel {{istio_channel}} --trust
    juju deploy -m {{_mesh}} istio-ingress-k8s --channel {{istio_channel}} --trust
    juju wait-for application -m {{_mesh}} istio-k8s         --query='status=="active"' --timeout=15m
    juju wait-for application -m {{_mesh}} istio-ingress-k8s --query='status=="active"' --timeout=15m

deploy-configurator:
    juju deploy -m {{_mesh}} ingress-configurator --channel {{ic_channel}}

deploy-haproxy:
    juju deploy -m {{_proxy}} haproxy --channel {{haproxy_channel}}
    juju wait-for application -m {{_proxy}} haproxy --query='status=="active"' --timeout=15m

# --- wiring (cross-model, cross-controller) ----------------------------------

relate:
    # Offer haproxy's TCP route endpoint from the LXD controller...
    juju offer {{lxd_ctrl}}:admin/{{proxy}}.haproxy:haproxy-route-tcp
    # ...consume it in the k8s model and integrate with the configurator.
    juju consume -m {{_mesh}} {{lxd_ctrl}}:admin/{{proxy}}.haproxy || true
    juju integrate -m {{_mesh}} ingress-configurator:haproxy-route-tcp haproxy

# --- configuration -----------------------------------------------------------
# Point ingress-configurator's TCP backend at the istio-ingress LB IP (TLS off = HTTP passthrough).
configure:
    #!/usr/bin/env bash
    set -euo pipefail
    LB=$(just _istio-lb)
    echo "istio-ingress LB IP: ${LB}"
    juju config -m {{_mesh}} ingress-configurator \
        tcp-backend-addresses="${LB}" \
        tcp-port-mapping="{{frontend_port}}:{{backend_port}}" \
        tcp-enforce-tls=false \
        tcp-tls-terminate=false
    juju config -m {{_proxy}} haproxy external-hostname=haproxy.internal
    juju wait-for application -m {{_mesh}}  ingress-configurator --query='status=="active"' --timeout=10m
    juju wait-for application -m {{_proxy}} haproxy              --query='status=="active"' --timeout=10m

# Optional: TLS passthrough (SNI-routed). haproxy does NOT terminate TLS; istio does.
# istio-ingress gets a cert from self-signed-certificates and serves HTTPS :443 for `tls_host`.
# haproxy inspects the TLS ClientHello SNI and forwards the encrypted stream unchanged.
tls_host := "bookinfo.test"

tls-passthrough: _tls-certs _tls-configure verify-passthrough

# Deploy self-signed-certificates in both models and wire certs.
# (SSC on the haproxy side is unused for passthrough; included to mirror the requested setup.)
_tls-certs:
    juju deploy -m {{_mesh}}  self-signed-certificates --channel latest/stable || true
    juju deploy -m {{_proxy}} self-signed-certificates --channel latest/stable || true
    juju integrate -m {{_mesh}}  self-signed-certificates:certificates istio-ingress-k8s:certificates || true
    juju integrate -m {{_proxy}} self-signed-certificates:certificates haproxy:certificates || true
    juju config -m {{_mesh}} istio-ingress-k8s external_hostname={{tls_host}}
    juju wait-for application -m {{_mesh}} istio-ingress-k8s --query='status=="active"' --timeout=15m

# Configure the configurator for SNI passthrough on 443 (tls terminate OFF, SNI = tls_host).
_tls-configure:
    juju config -m {{_mesh}} ingress-configurator \
        tcp-port-mapping=443:443 \
        tcp-tls-terminate=false \
        tcp-enforce-tls=true \
        tcp-hostname={{tls_host}}
    juju wait-for application -m {{_mesh}} ingress-configurator --query='status=="active"' --timeout=10m

# Prove passthrough: HTTPS 200 through haproxy, and the served cert is istio's (SSC-issued).
verify-passthrough:
    #!/usr/bin/env bash
    set -euo pipefail
    HAP=$(just _haproxy-addr)
    URL="https://{{tls_host}}/mesh-bookinfo-productpage-k8s/productpage"
    echo "== HTTPS through haproxy (SNI={{tls_host}}) =="
    curl -sk -o /dev/null -w "  http_code=%{http_code}\n" --max-time 12 \
        --resolve {{tls_host}}:443:${HAP} "${URL}"
    echo "== cert presented through haproxy (expect CN={{tls_host}}, issued by SSC = istio's cert) =="
    echo | openssl s_client -connect ${HAP}:443 -servername {{tls_host}} 2>/dev/null \
        | openssl x509 -noout -subject -issuer


# --- verification ------------------------------------------------------------

verify:
    #!/usr/bin/env bash
    set -euo pipefail
    LB=$(just _istio-lb)
    HAP=$(just _haproxy-addr)
    echo "== direct to istio-ingress (${LB}:{{backend_port}}) =="
    curl -s -o /dev/null -w "  http_code=%{http_code}\n" --max-time 8 "http://${LB}:{{backend_port}}/"
    echo "== through haproxy (${HAP}:{{frontend_port}}) =="
    curl -s -i --max-time 8 "http://${HAP}:{{frontend_port}}/" | head -4
    echo "(expect 'server: istio-envoy' -> proves the TCP path reaches istio; 404 is normal with no backend app)"

status:
    -juju status -m {{_mesh}} --relations
    -juju status -m {{_proxy}} --relations

# --- teardown ----------------------------------------------------------------

clean:
    -juju remove-offer -y {{lxd_ctrl}}:admin/{{proxy}}.haproxy --force
    -juju destroy-model -y --no-prompt {{_mesh}}  --destroy-storage --force
    -juju destroy-model -y --no-prompt {{_proxy}} --destroy-storage --force

# --- helpers -----------------------------------------------------------------
# istio-ingress advertises its LB IP in its workload status: "Serving at <IP>".
_istio-lb:
    @juju status -m {{_mesh}} --format json \
      | jq -r '.applications."istio-ingress-k8s".units | to_entries[0].value."workload-status".message' \
      | awk '{print $NF}'

_haproxy-addr:
    @juju status -m {{_proxy}} --format json \
      | jq -r '.applications.haproxy.units."haproxy/0"."public-address"'
