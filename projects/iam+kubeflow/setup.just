# Kubeflow + IAM integration via Istio Ingress
#
# Architecture:
#   Traefik (iam) -> ingress (forward-auth + oauth2-proxy) -> kubeflow-dashboard  [browser login]
#
# Three models: istio-system, iam, kubeflow
# Requires: juju bootstrapped to microk8s with dns,hostpath-storage,metallb addons

model-istio := "istio-system"
model-iam := "iam"
model-kubeflow := "kubeflow"

# --- channels ---
# IAM charms: latest/stable (latest/edge has kratos identifier_first bug vs login-ui)
ch-postgresql := "14/stable"
ch-hydra := "latest/stable"
ch-kratos := "latest/stable"
ch-login-ui := "latest/stable"
ch-traefik := "latest/stable"
# self-signed-certs: 1/stable for V1 certificate-transfer format (V0 breaks istio/traefik)
ch-self-signed-certs := "1/stable"
# istio + ingress: dev/edge for latest features
ch-istio-k8s := "dev/edge"
ch-istio-ingress := "dev/edge"
# oauth2-proxy
ch-oauth2-proxy := "latest/edge"
# kubeflow charms
ch-kubeflow := "latest/edge"

# name of the istio ingress charm deployed in the kubeflow model
# the service account created by the charm is <ingress-app>-istio
ingress-app := "ingress"

# domain traefik advertises (set in /etc/hosts and CoreDNS)
domain := "app.example.com"

# --- idempotent helpers ---

[private]
_add-model name:
    juju add-model {{name}} 2>/dev/null || true

[private]
_deploy model charm app channel +args="":
    juju deploy -m {{model}} {{charm}} {{app}} --channel {{channel}} --trust {{args}} 2>/dev/null || true

[private]
_integrate model a b:
    juju integrate -m {{model}} {{a}} {{b}} 2>/dev/null || true

[private]
_offer source name:
    juju offer {{source}} {{name}} 2>/dev/null || true

[private]
_consume source model:
    juju consume {{source}} --model {{model}} 2>/dev/null || true

[private]
_wait-for model app:
    @echo "waiting for {{app}} in {{model}}..."
    @juju wait-for application {{app}} -m {{model}} --query='status == "active"' --timeout 20m 2>/dev/null

# ============================================================
# Full setup
# ============================================================

setup: deploy-istio deploy-iam wait-iam deploy-kubeflow create-offers consume-offers integrate-cross-model wait-kubeflow configure-jwt #apply-envoyfilter
    @echo "=== Setup complete ==="
    @echo "Run 'just -f kubeflow_iam.just show-ingress-urls' to see URLs"

# ============================================================
# Teardown
# ============================================================

teardown:
    juju destroy-model {{model-kubeflow}} --no-prompt --destroy-storage --force 2>/dev/null || true
    juju destroy-model {{model-iam}} --no-prompt --destroy-storage --force 2>/dev/null || true
    juju destroy-model {{model-istio}} --no-prompt --destroy-storage --force 2>/dev/null || true

# ============================================================
# Status
# ============================================================

status:
    @echo "--- {{model-istio}} ---"
    juju status -m {{model-istio}} --format short 2>/dev/null || echo "(model not found)"
    @echo "--- {{model-iam}} ---"
    juju status -m {{model-iam}} --format short 2>/dev/null || echo "(model not found)"
    @echo "--- {{model-kubeflow}} ---"
    juju status -m {{model-kubeflow}} --format short 2>/dev/null || echo "(model not found)"

# ============================================================
# istio-system model
# ============================================================

## Configure Cilium to be compatible with Istio ambient/sidecar mode
## See https://docs.cilium.io/en/stable/network/servicemesh/istio/
#configure-cilium:
#    kubectl -n kube-system patch configmap cilium-config --type merge --patch '{"data":{"bpf-lb-sock-hostns-only":"true"}}'
#    kubectl -n kube-system patch configmap cilium-config --type merge --patch '{"data":{"cni-exclusive":"false"}}'
#    kubectl -n kube-system rollout restart daemonset cilium

deploy-istio: #configure-cilium
    just -f {{justfile()}} _add-model {{model-istio}}
    just -f {{justfile()}} _deploy {{model-istio}} istio-k8s istio-k8s {{ch-istio-k8s}}

# ============================================================
# IAM model
# ============================================================

deploy-iam: deploy-iam-charms configure-iam integrate-iam integrate-iam-tls

deploy-iam-charms:
    just -f {{justfile()}} _add-model {{model-iam}}
    just -f {{justfile()}} _deploy {{model-iam}} postgresql-k8s postgresql {{ch-postgresql}} \
        --config plugin_pg_trgm_enable=True \
        --config plugin_btree_gin_enable=True
    just -f {{justfile()}} _deploy {{model-iam}} hydra hydra {{ch-hydra}}
    just -f {{justfile()}} _deploy {{model-iam}} kratos kratos {{ch-kratos}}
    just -f {{justfile()}} _deploy {{model-iam}} identity-platform-login-ui-operator login-ui {{ch-login-ui}}
    just -f {{justfile()}} _deploy {{model-iam}} traefik-k8s traefik {{ch-traefik}}
    just -f {{justfile()}} _deploy {{model-iam}} self-signed-certificates self-signed-certs {{ch-self-signed-certs}}

configure-iam:
    # kratos needs dev mode for HTTP internally
    juju config -m {{model-iam}} kratos dev=true
    # disable MFA so users can log in with just a password
    juju config -m {{model-iam}} kratos enforce_mfa=false

integrate-iam:
    # database
    just -f {{justfile()}} _integrate {{model-iam}} hydra:pg-database postgresql:database
    just -f {{justfile()}} _integrate {{model-iam}} kratos:pg-database postgresql:database
    # hydra <-> kratos <-> login-ui
    just -f {{justfile()}} _integrate {{model-iam}} kratos:hydra-endpoint-info hydra:hydra-endpoint-info
    just -f {{justfile()}} _integrate {{model-iam}} login-ui:hydra-endpoint-info hydra:hydra-endpoint-info
    just -f {{justfile()}} _integrate {{model-iam}} login-ui:ui-endpoint-info hydra:ui-endpoint-info
    just -f {{justfile()}} _integrate {{model-iam}} login-ui:ui-endpoint-info kratos:ui-endpoint-info
    just -f {{justfile()}} _integrate {{model-iam}} login-ui:kratos-info kratos:kratos-info
    # public routes via traefik
    just -f {{justfile()}} _integrate {{model-iam}} hydra:public-route traefik
    just -f {{justfile()}} _integrate {{model-iam}} kratos:public-route traefik
    just -f {{justfile()}} _integrate {{model-iam}} login-ui:public-route traefik

integrate-iam-tls:
    # TLS on traefik - login-ui hardcodes https in normalise_url
    just -f {{justfile()}} _integrate {{model-iam}} self-signed-certs:certificates traefik:certificates
    # CA cert so kratos and login-ui trust traefik's TLS
    just -f {{justfile()}} _integrate {{model-iam}} self-signed-certs:send-ca-cert kratos:receive-ca-cert
    just -f {{justfile()}} _integrate {{model-iam}} self-signed-certs:send-ca-cert login-ui:receive-ca-cert

wait-iam:
    just -f {{justfile()}} _wait-for {{model-iam}} hydra
    just -f {{justfile()}} _wait-for {{model-iam}} self-signed-certs

wait-kubeflow:
    just -f {{justfile()}} _wait-for {{model-kubeflow}} {{ingress-app}}
    just -f {{justfile()}} _wait-for {{model-kubeflow}} oauth2-proxy
    just -f {{justfile()}} _wait-for {{model-kubeflow}} kubeflow-dashboard
    just -f {{justfile()}} _wait-for {{model-kubeflow}} kubeflow-profiles
    just -f {{justfile()}} _wait-for {{model-kubeflow}} kserve-controller
    just -f {{justfile()}} _wait-for {{model-kubeflow}} jupyter-controller
    just -f {{justfile()}} _wait-for {{model-kubeflow}} jupyter-ui

# ============================================================
# Kubeflow model
# ============================================================

deploy-kubeflow: deploy-kubeflow-charms configure-kubeflow integrate-kubeflow

deploy-kubeflow-charms:
    just -f {{justfile()}} _add-model {{model-kubeflow}}
    # istio ingress gateway for the kubeflow model
    just -f {{justfile()}} _deploy {{model-kubeflow}} istio-ingress-k8s {{ingress-app}} {{ch-istio-ingress}}
    # oauth2-proxy for browser auth (forward-auth)
    just -f {{justfile()}} _deploy {{model-kubeflow}} oauth2-proxy-k8s oauth2-proxy {{ch-oauth2-proxy}}
    # kubeflow charms
    just -f {{justfile()}} _deploy {{model-kubeflow}} kubeflow-dashboard kubeflow-dashboard latest/edge/pr-325
    just -f {{justfile()}} _deploy {{model-kubeflow}} kubeflow-profiles kubeflow-profiles {{ch-kubeflow}} \
        --config istio-gateway-service-account={{ingress-app}}-istio \
        --config service-mesh-mode=istio-ambient
    just -f {{justfile()}} _deploy {{model-kubeflow}} kserve-controller kserve-controller {{ch-kubeflow}} \
        --config deployment-mode=Standard

    just -f {{justfile()}} _deploy {{model-kubeflow}} jupyter-controller jupyter-controller {{ch-kubeflow}}
    just -f {{justfile()}} _deploy {{model-kubeflow}} jupyter-ui jupyter-ui {{ch-kubeflow}}
    # istio beacon for service mesh enrolment
    just -f {{justfile()}} _deploy {{model-kubeflow}} istio-beacon-k8s istio-beacon {{ch-istio-ingress}}
    # self-signed-certs for ingress TLS + CA sharing with traefik
    just -f {{justfile()}} _deploy {{model-kubeflow}} self-signed-certificates self-signed-certs {{ch-self-signed-certs}}

configure-kubeflow:
    # oauth2-proxy: dev=true sets SSL_INSECURE_SKIP_VERIFY (receive-ca-cert data is ignored by the charm)
    juju config -m {{model-kubeflow}} oauth2-proxy dev=true enable_jwt_bearer_tokens=true

integrate-kubeflow:
    # ingress: forward-auth (browser login) + oauth2-proxy's own ingress
    just -f {{justfile()}} _integrate {{model-kubeflow}} oauth2-proxy:forward-auth {{ingress-app}}:forward-auth
    just -f {{justfile()}} _integrate {{model-kubeflow}} oauth2-proxy:ingress {{ingress-app}}:ingress-unauthenticated
    # kubeflow-dashboard exposed via the ingress (JWT/request-auth + ingress route)
    just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-dashboard:login-request-auth {{ingress-app}}:istio-request-auth
    # For M2M only
    # just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-dashboard:m2m-request-auth {{ingress-app}}
    just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-dashboard:istio-ingress-route {{ingress-app}}:istio-ingress-route
    # kubeflow-dashboard <-> kubeflow-profiles
    just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-dashboard:kubeflow-profiles kubeflow-profiles:profiles
    just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-dashboard:kubeflow-profiles kubeflow-profiles
    # enrol kubeflow charms into the service mesh via istio-beacon
    just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-dashboard:service-mesh istio-beacon:service-mesh
    just -f {{justfile()}} _integrate {{model-kubeflow}} kserve-controller:service-mesh istio-beacon:service-mesh
    just -f {{justfile()}} _integrate {{model-kubeflow}} kubeflow-profiles:service-mesh istio-beacon:service-mesh
    # kserve-controller gateway metadata from istio ingress
    just -f {{justfile()}} _integrate {{model-kubeflow}} kserve-controller:gateway-metadata {{ingress-app}}:gateway-metadata
    # jupyter: service mesh enrolment, gateway metadata, ingress route, dashboard links
    just -f {{justfile()}} _integrate {{model-kubeflow}} jupyter-controller:service-mesh istio-beacon:service-mesh
    just -f {{justfile()}} _integrate {{model-kubeflow}} jupyter-ui:service-mesh istio-beacon:service-mesh
    just -f {{justfile()}} _integrate {{model-kubeflow}} jupyter-controller:gateway-metadata {{ingress-app}}:gateway-metadata
    just -f {{justfile()}} _integrate {{model-kubeflow}} jupyter-ui:istio-ingress-route {{ingress-app}}:istio-ingress-route
    just -f {{justfile()}} _integrate {{model-kubeflow}} jupyter-ui:dashboard-links kubeflow-dashboard:links
    # TLS on ingress
    just -f {{justfile()}} _integrate {{model-kubeflow}} self-signed-certs:certificates {{ingress-app}}:certificates

# ============================================================
# Cross-model offers, consumes, and integrations
# ============================================================

create-offers:
    # istio-system -> kubeflow: istio mesh config for the gateway
    just -f {{justfile()}} _offer {{model-istio}}.istio-k8s:istio-ingress-config istio-ingress-config
    # iam -> kubeflow: hydra OAuth for oauth2-proxy
    just -f {{justfile()}} _offer {{model-iam}}.hydra:oauth hydra-oauth
    # iam -> kubeflow: CA cert so oauth2-proxy trusts traefik's TLS
    just -f {{justfile()}} _offer {{model-iam}}.self-signed-certs:send-ca-cert iam-ca-cert
    ## iam -> kubeflow: traefik ingress for upstream-ingress on the gateway
    #just -f {{justfile()}} _offer {{model-iam}}.traefik:ingress traefik-ingress
    # kubeflow -> iam: CA cert so traefik trusts istio gateway TLS
    just -f {{justfile()}} _offer {{model-kubeflow}}.self-signed-certs:send-ca-cert kubeflow-ca

consume-offers:
    just -f {{justfile()}} _consume admin/{{model-istio}}.istio-ingress-config {{model-kubeflow}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.hydra-oauth {{model-kubeflow}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.iam-ca-cert {{model-kubeflow}}
    #just -f {{justfile()}} _consume admin/{{model-iam}}.traefik-ingress {{model-kubeflow}}
    # istio-system consumes iam CA for JWKS trust
    just -f {{justfile()}} _consume admin/{{model-iam}}.iam-ca-cert {{model-istio}}
    # iam consumes kubeflow CA so traefik trusts istio gateway certs
    just -f {{justfile()}} _consume admin/{{model-kubeflow}}.kubeflow-ca {{model-iam}}

integrate-cross-model:
    # gateway gets istio mesh config
    just -f {{justfile()}} _integrate {{model-kubeflow}} {{ingress-app}}:istio-ingress-config istio-ingress-config
    # oauth2-proxy -> hydra OAuth
    just -f {{justfile()}} _integrate {{model-kubeflow}} oauth2-proxy:oauth hydra-oauth
    # oauth2-proxy trusts traefik's TLS
    just -f {{justfile()}} _integrate {{model-kubeflow}} oauth2-proxy:receive-ca-cert iam-ca-cert
    ## gateway behind traefik via upstream-ingress
    #just -f {{justfile()}} _integrate {{model-kubeflow}} {{ingress-app}}:upstream-ingress traefik-ingress
    # istiod trusts iam CA for JWKS endpoint
    just -f {{justfile()}} _integrate {{model-istio}} istio-k8s:jwks-ca-cert iam-ca-cert
    # traefik trusts kubeflow CA for istio gateway TLS (endToEndTLS)
    just -f {{justfile()}} _integrate {{model-iam}} traefik:receive-ca-cert kubeflow-ca

# ============================================================
# JWT configuration
# ============================================================

# Configure kubeflow-dashboard JWT issuer to match hydra's issuer behind traefik
# Uses traefik's external LB IP by default; run enable-hostname to switch to domain
configure-jwt:
    #!/usr/bin/env bash
    set -euo pipefail
    ISSUER_HOST=$(kubectl -n {{model-iam}} get svc traefik-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null \
        || kubectl -n {{model-iam}} get svc -l app.kubernetes.io/name=traefik-k8s -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}')
    echo "Configuring JWT issuer to https://$ISSUER_HOST"
    juju config -m {{model-kubeflow}} kubeflow-dashboard \
        jwt-issuer="https://$ISSUER_HOST"

## ============================================================
## EnvoyFilter for X-Forwarded-Uri (fixes post-login redirect 404)
## ============================================================
#
## Traefik's stripPrefix removes the path prefix before forwarding.
## oauth2-proxy only sees the stripped path for redirect.
## This Lua filter combines X-Forwarded-Prefix + request path into X-Forwarded-Uri
## before the ext_authz check so oauth2-proxy redirects to the full path.
#apply-envoyfilter:
#    #!/usr/bin/env bash
#    set -euo pipefail
#    cat <<'EOF' | kubectl apply -n {{model-kubeflow}} -f -
#    apiVersion: networking.istio.io/v1alpha3
#    kind: EnvoyFilter
#    metadata:
#      name: set-x-forwarded-uri
#    spec:
#      workloadSelector:
#        labels:
#          gateway.networking.k8s.io/gateway-name: {{ingress-app}}
#      configPatches:
#      - applyTo: HTTP_FILTER
#        match:
#          context: GATEWAY
#          listener:
#            filterChain:
#              filter:
#                name: envoy.filters.network.http_connection_manager
#                subFilter:
#                  name: envoy.filters.http.ext_authz
#        patch:
#          operation: INSERT_BEFORE
#          value:
#            name: envoy.filters.http.lua
#            typed_config:
#              "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua
#              inline_code: |
#                function envoy_on_request(handle)
#                  local prefix = handle:headers():get("x-forwarded-prefix")
#                  if prefix then
#                    local path = handle:headers():get(":path")
#                    handle:headers():replace("x-forwarded-uri", prefix .. path)
#                  end
#                end
#    EOF
#    echo "EnvoyFilter applied"

# ============================================================
# Domain + DNS configuration
# ============================================================

# Set external_hostname on traefik (by default traefik uses its LB IP)
configure-domain:
    juju config -m {{model-iam}} traefik external_hostname={{domain}}

# Full hostname setup: set domain + patch CoreDNS
enable-hostname:
    #!/usr/bin/env bash
    set -euo pipefail
    # set hostname on traefik
    juju config -m {{model-iam}} traefik external_hostname={{domain}}
    # get traefik's ClusterIP (works even without external LB)
    TRAEFIK_IP=$(kubectl -n iam get svc traefik-lb -o jsonpath='{.spec.clusterIP}' 2>/dev/null \
        || kubectl -n iam get svc -l app.kubernetes.io/name=traefik-k8s -o jsonpath='{.items[0].spec.clusterIP}')
    echo "Traefik ClusterIP: $TRAEFIK_IP"
    # patch CoreDNS
    CURRENT=$(kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')
    if echo "$CURRENT" | grep -q "{{domain}}"; then
        echo "CoreDNS already has {{domain}} entry, updating IP..."
        PATCHED=$(echo "$CURRENT" | sed "s/[0-9.]\+ {{domain}}/$TRAEFIK_IP {{domain}}/")
    else
        PATCHED=$(echo "$CURRENT" | sed "/kubernetes cluster.local/i \
        hosts {\n            $TRAEFIK_IP {{domain}}\n            fallthrough\n        }")
    fi
    kubectl -n kube-system create configmap coredns --from-literal=Corefile="$PATCHED" --dry-run=client -o yaml \
        | kubectl apply -f -
    kubectl -n kube-system rollout restart deployment/coredns
    echo "Done. {{domain}} -> $TRAEFIK_IP in CoreDNS"

# Manual CoreDNS patch (prefer enable-hostname which does this automatically)
patch-coredns traefik_ip:
    #!/usr/bin/env bash
    set -euo pipefail
    CURRENT=$(kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')
    if echo "$CURRENT" | grep -q "{{domain}}"; then
        echo "CoreDNS already has {{domain}} entry"
        exit 0
    fi
    PATCHED=$(echo "$CURRENT" | sed '/kubernetes cluster.local/i \
        hosts {\
            {{traefik_ip}} {{domain}}\
            fallthrough\
        }')
    kubectl -n kube-system create configmap coredns --from-literal=Corefile="$PATCHED" --dry-run=client -o yaml \
        | kubectl apply -f -
    kubectl -n kube-system rollout restart deployment/coredns

# ============================================================
# Show ingress URLs
# ============================================================

show-ingress-urls:
    #!/usr/bin/env bash
    set -euo pipefail
    TRAEFIK_IP=$(kubectl -n {{model-iam}} get svc traefik-lb \
        -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null \
        || kubectl -n {{model-iam}} get svc -l app.kubernetes.io/name=traefik-k8s \
        -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}')
    echo "Traefik LB IP: $TRAEFIK_IP"
    echo "KubeFlow Dashboard: https://$TRAEFIK_IP/kubeflow-dashboard"

# ============================================================
# User management
# ============================================================

# create an admin account in kratos and a matching kubeflow Profile
# usage: just -f kubeflow_iam.just create-admin admin admin@email.com
create-admin name email:
    just -f {{justfile()}} create-kratos-admin {{name}} {{email}}
    just -f {{justfile()}} create-kubeflow-profile {{name}} {{email}}

# create the kratos admin account
create-kratos-admin name email:
    juju run -m {{model-iam}} kratos/0 create-admin-account username={{name}} email={{email}}

# create a kubeflow Profile for a user
# usage: just -f kubeflow_iam.just create-kubeflow-profile admin admin@email.com
create-kubeflow-profile name email:
    #!/usr/bin/env bash
    set -euo pipefail
    cat <<EOF | kubectl apply -f -
    apiVersion: kubeflow.org/v1
    kind: Profile
    metadata:
      name: {{name}}
    spec:
      owner:
        kind: User
        name: {{email}}
    EOF
    echo "Profile '{{name}}' created for {{email}}"

# create a test user in kratos
create-user email password:
    #!/usr/bin/env bash
    set -euo pipefail
    IDENTITY_ID=$(kubectl -n {{model-iam}} exec kratos-0 -c kratos -- \
        kratos import identities --endpoint http://localhost:4434 /dev/stdin <<EOIDENT | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])"
    [{
      "schema_id": "default",
      "traits": {"email": "{{email}}"},
      "credentials": {
        "password": {
          "config": {"password": "{{password}}"}
        }
      }
    }]
    EOIDENT
    )
    echo "Created identity: $IDENTITY_ID"
