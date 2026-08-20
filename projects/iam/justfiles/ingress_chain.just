# Dual Istio Ingress via Traefik: browser auth (forward-auth) + JWT auth (request-auth)
#
# Architecture:
#   Traefik (iam) -> ingress1 (forward-auth + oauth2-proxy)  -> productpage2  [browser login]
#                 -> ingress2 (request-auth via productpage2) -> productpage2  [JWT bearer]
#
# Three models: istio-system, iam, bookinfo
# Requires: juju bootstrapped to microk8s with dns,hostpath-storage,metallb addons

model-istio := "istio-system"
model-iam := "iam"
model-bookinfo := "bookinfo"

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
# bookinfo + oauth2-proxy
ch-oauth2-proxy := "latest/edge"
ch-bookinfo := "latest/stable"
ch-details := "latest/stable"

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

setup: deploy-istio deploy-iam wait-iam deploy-bookinfo create-offers consume-offers integrate-cross-model wait-bookinfo configure-jwt apply-envoyfilter
    @echo "=== Setup complete ==="
    @echo "Run 'just -f ingress_chain.just show-ingress-urls' to see URLs"
    @echo "Run 'just -f ingress_chain.just enable-hostname' to switch to domain-based routing"

# ============================================================
# Teardown
# ============================================================

teardown:
    juju destroy-model {{model-bookinfo}} --no-prompt --destroy-storage --force 2>/dev/null || true
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
    @echo "--- {{model-bookinfo}} ---"
    juju status -m {{model-bookinfo}} --format short 2>/dev/null || echo "(model not found)"

# ============================================================
# istio-system model
# ============================================================

deploy-istio:
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

wait-bookinfo:
    just -f {{justfile()}} _wait-for {{model-bookinfo}} ingress1
    just -f {{justfile()}} _wait-for {{model-bookinfo}} ingress2
    just -f {{justfile()}} _wait-for {{model-bookinfo}} oauth2-proxy
    just -f {{justfile()}} _wait-for {{model-bookinfo}} productpage2

# ============================================================
# Bookinfo model (dual gateway)
# ============================================================

deploy-bookinfo: deploy-bookinfo-charms configure-bookinfo integrate-bookinfo

deploy-bookinfo-charms:
    just -f {{justfile()}} _add-model {{model-bookinfo}}
    # ingress1: browser auth (forward-auth via oauth2-proxy)
    just -f {{justfile()}} _deploy {{model-bookinfo}} istio-ingress-k8s ingress1 {{ch-istio-ingress}}
    # ingress2: JWT auth (request-auth via productpage2)
    just -f {{justfile()}} _deploy {{model-bookinfo}} istio-ingress-k8s ingress2 {{ch-istio-ingress}}
    # oauth2-proxy for browser auth on ingress1
    just -f {{justfile()}} _deploy {{model-bookinfo}} oauth2-proxy-k8s oauth2-proxy {{ch-oauth2-proxy}}
    # productpage2: custom build with istio-request-auth support
    just -f {{justfile()}} _deploy {{model-bookinfo}} bookinfo-productpage-k8s productpage2 {{ch-bookinfo}}
    # details backend
    just -f {{justfile()}} _deploy {{model-bookinfo}} bookinfo-details-k8s details {{ch-details}}
    # self-signed-certs for ingress TLS + CA sharing with traefik
    just -f {{justfile()}} _deploy {{model-bookinfo}} self-signed-certificates self-signed-certs {{ch-self-signed-certs}}

configure-bookinfo:
    # oauth2-proxy: dev=true sets SSL_INSECURE_SKIP_VERIFY (receive-ca-cert data is ignored by the charm)
    juju config -m {{model-bookinfo}} oauth2-proxy dev=true

integrate-bookinfo:
    # ingress1: forward-auth (browser login) + oauth2-proxy's own ingress
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:forward-auth ingress1:forward-auth
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:ingress ingress1:ingress-unauthenticated
    # both gateways route to productpage2
    just -f {{justfile()}} _integrate {{model-bookinfo}} productpage2:ingress ingress1:ingress
    just -f {{justfile()}} _integrate {{model-bookinfo}} productpage2:ingress ingress2:ingress
    # ingress2: request-auth (JWT validation) via productpage2
    just -f {{justfile()}} _integrate {{model-bookinfo}} productpage2:istio-request-auth ingress2:istio-request-auth
    # productpage2 -> details backend
    just -f {{justfile()}} _integrate {{model-bookinfo}} productpage2:details details:details
    # TLS on ingress1 (redirect_uri must be https for hydra CSRF cookies)
    just -f {{justfile()}} _integrate {{model-bookinfo}} self-signed-certs:certificates ingress1:certificates
    just -f {{justfile()}} _integrate {{model-bookinfo}} self-signed-certs:certificates ingress2:certificates

# ============================================================
# Cross-model offers, consumes, and integrations
# ============================================================

create-offers:
    # istio-system -> bookinfo: istio mesh config for both gateways
    just -f {{justfile()}} _offer {{model-istio}}.istio-k8s:istio-ingress-config istio-ingress-config
    # iam -> bookinfo: hydra OAuth for oauth2-proxy
    just -f {{justfile()}} _offer {{model-iam}}.hydra:oauth hydra-oauth
    # iam -> bookinfo: CA cert so oauth2-proxy trusts traefik's TLS
    just -f {{justfile()}} _offer {{model-iam}}.self-signed-certs:send-ca-cert iam-ca-cert
    # iam -> bookinfo: traefik ingress for upstream-ingress on both gateways
    just -f {{justfile()}} _offer {{model-iam}}.traefik:ingress traefik-ingress
    # iam -> istio-system: CA cert so istiod trusts JWKS endpoint TLS
    # (uses same iam-ca-cert offer, consumed separately in istio-system)
    # bookinfo -> iam: CA cert so traefik trusts istio gateway TLS
    just -f {{justfile()}} _offer {{model-bookinfo}}.self-signed-certs:send-ca-cert bookinfo-ca

consume-offers:
    just -f {{justfile()}} _consume admin/{{model-istio}}.istio-ingress-config {{model-bookinfo}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.hydra-oauth {{model-bookinfo}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.iam-ca-cert {{model-bookinfo}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.traefik-ingress {{model-bookinfo}}
    # istio-system consumes iam CA for JWKS trust
    just -f {{justfile()}} _consume admin/{{model-iam}}.iam-ca-cert {{model-istio}}
    # iam consumes bookinfo CA so traefik trusts istio gateway certs
    just -f {{justfile()}} _consume admin/{{model-bookinfo}}.bookinfo-ca {{model-iam}}

integrate-cross-model:
    # both gateways get istio mesh config
    just -f {{justfile()}} _integrate {{model-bookinfo}} ingress1:istio-ingress-config istio-ingress-config
    just -f {{justfile()}} _integrate {{model-bookinfo}} ingress2:istio-ingress-config istio-ingress-config
    # oauth2-proxy -> hydra OAuth
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:oauth hydra-oauth
    # oauth2-proxy trusts traefik's TLS
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:receive-ca-cert iam-ca-cert
    # both gateways behind traefik via upstream-ingress
    just -f {{justfile()}} _integrate {{model-bookinfo}} ingress1:upstream-ingress traefik-ingress
    just -f {{justfile()}} _integrate {{model-bookinfo}} ingress2:upstream-ingress traefik-ingress
    # istiod trusts iam CA for JWKS endpoint
    just -f {{justfile()}} _integrate {{model-istio}} istio-k8s:jwks-ca-cert iam-ca-cert
    # traefik trusts bookinfo CA for istio gateway TLS (endToEndTLS)
    just -f {{justfile()}} _integrate {{model-iam}} traefik:receive-ca-cert bookinfo-ca

# ============================================================
# Domain + DNS configuration
# ============================================================

# configure traefik domain and productpage JWT settings
# run after traefik is active and has its LB IP
# Set external_hostname on traefik (by default traefik uses its LB IP)
configure-domain:
    juju config -m {{model-iam}} traefik external_hostname={{domain}}

# Full hostname setup: set domain + patch CoreDNS + update JWT config
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
    # update JWT config to use domain
    juju config -m {{model-bookinfo}} productpage2 \
        jwt-issuer=https://{{domain}} \
        jwt-jwks-uri=https://{{domain}}/.well-known/jwks.json
    echo "JWT config updated to use {{domain}}"

# configure productpage2 JWT to match hydra's issuer behind traefik
# uses traefik's external LB IP by default; enable-hostname switches to domain
configure-jwt:
    #!/usr/bin/env bash
    set -euo pipefail
    ISSUER_HOST=$(kubectl -n {{model-iam}} get svc traefik-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null \
        || kubectl -n {{model-iam}} get svc -l app.kubernetes.io/name=traefik-k8s -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}')
    echo "Configuring JWT issuer to https://$ISSUER_HOST"
    juju config -m {{model-bookinfo}} productpage2 \
        jwt-issuer="https://$ISSUER_HOST" \
        jwt-jwks-uri="https://$ISSUER_HOST/.well-known/jwks.json"

# Manual CoreDNS patch (prefer enable-hostname which does this automatically)
# requires: traefik LB IP
patch-coredns traefik_ip:
    #!/usr/bin/env bash
    set -euo pipefail
    CURRENT=$(kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}')
    if echo "$CURRENT" | grep -q "{{domain}}"; then
        echo "CoreDNS already has {{domain}} entry"
        exit 0
    fi
    # insert hosts block before the first kubernetes block
    PATCHED=$(echo "$CURRENT" | sed '/kubernetes cluster.local/i \
        hosts {\
            {{traefik_ip}} {{domain}}\
            fallthrough\
        }')
    kubectl -n kube-system create configmap coredns --from-literal=Corefile="$PATCHED" --dry-run=client -o yaml \
        | kubectl apply -f -
    kubectl -n kube-system rollout restart deployment/coredns

# ============================================================
# EnvoyFilter for X-Forwarded-Uri (fixes post-login redirect 404)
# ============================================================

# Traefik's stripPrefix removes /bookinfo-ingress1 before forwarding.
# oauth2-proxy only sees the stripped path for redirect.
# This Lua filter combines X-Forwarded-Prefix + request path into X-Forwarded-Uri
# before the ext_authz check so oauth2-proxy redirects to the full path.
apply-envoyfilter:
    #!/usr/bin/env bash
    set -euo pipefail
    cat <<'EOF' | kubectl apply -n {{model-bookinfo}} -f -
    apiVersion: networking.istio.io/v1alpha3
    kind: EnvoyFilter
    metadata:
      name: set-x-forwarded-uri
    spec:
      workloadSelector:
        labels:
          gateway.networking.k8s.io/gateway-name: ingress1
      configPatches:
      - applyTo: HTTP_FILTER
        match:
          context: GATEWAY
          listener:
            filterChain:
              filter:
                name: envoy.filters.network.http_connection_manager
                subFilter:
                  name: envoy.filters.http.ext_authz
        patch:
          operation: INSERT_BEFORE
          value:
            name: envoy.filters.http.lua
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua
              inline_code: |
                function envoy_on_request(handle)
                  local prefix = handle:headers():get("x-forwarded-prefix")
                  if prefix then
                    local path = handle:headers():get(":path")
                    handle:headers():replace("x-forwarded-uri", prefix .. path)
                  end
                end
    EOF
    echo "EnvoyFilter applied"

# ============================================================
# User + M2M client management
# ============================================================

# create a test user in kratos
create-user email password:
    #!/usr/bin/env bash
    set -euo pipefail
    # create identity
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

# get the oauth2-proxy client_id from the oauth relation
get-oauth2-proxy-client-id:
    #!/usr/bin/env bash
    juju show-unit -m {{model-bookinfo}} oauth2-proxy/0 --format json \
        | python3 -c "
    import sys, json
    data = json.load(sys.stdin)['oauth2-proxy/0']
    for ri in data['relation-info']:
        if ri['endpoint'] == 'oauth':
            print(ri['application-data']['client_id'])
            break
    "

# create an M2M client in hydra for client_credentials JWT flow
create-m2m-client:
    #!/usr/bin/env bash
    AUDIENCE=$(just -f {{justfile()}} get-oauth2-proxy-client-id)
    kubectl -n {{model-iam}} exec hydra-0 -c hydra -- \
        hydra create oauth2-client \
        --endpoint http://localhost:4445 \
        --name "test-m2m-client" \
        --grant-type client_credentials \
        --response-type token \
        --scope "openid email" \
        --audience "$AUDIENCE" \
        --format json

# get a JWT using client_credentials flow
get-token client_id client_secret:
    #!/usr/bin/env bash
    AUDIENCE=$(just -f {{justfile()}} get-oauth2-proxy-client-id)
    curl -sk -X POST "https://{{domain}}/oauth2/token" \
        -u "{{client_id}}:{{client_secret}}" \
        -d "grant_type=client_credentials&scope=openid+email&audience=$AUDIENCE" \
        | python3 -m json.tool

# ============================================================
# Test recipes
# ============================================================

# test browser auth path - should get 302 redirect to login
test-browser-auth:
    #!/usr/bin/env bash
    echo "--- Browser auth (ingress1): expecting 302 redirect ---"
    STATUS=$(curl -sk -o /dev/null -w '%{http_code}' \
        "https://{{domain}}/bookinfo-ingress1/bookinfo-productpage2")
    echo "HTTP $STATUS"
    if [ "$STATUS" = "302" ]; then echo "✓ PASS"; else echo "✗ FAIL (expected 302)"; fi

# test JWT auth path without token - should get 403
test-jwt-notoken:
    #!/usr/bin/env bash
    echo "--- JWT auth (ingress2) without token: expecting 403 ---"
    STATUS=$(curl -sk -o /dev/null -w '%{http_code}' \
        "https://{{domain}}/bookinfo-ingress2/bookinfo-productpage2")
    echo "HTTP $STATUS"
    if [ "$STATUS" = "403" ]; then echo "✓ PASS"; else echo "✗ FAIL (expected 403)"; fi

# test JWT auth path with valid token - should get 200
test-jwt client_id client_secret:
    #!/usr/bin/env bash
    echo "--- JWT auth (ingress2) with token: expecting 200 ---"
    AUDIENCE=$(just -f {{justfile()}} get-oauth2-proxy-client-id)
    TOKEN=$(curl -sk -X POST "https://{{domain}}/oauth2/token" \
        -u "{{client_id}}:{{client_secret}}" \
        -d "grant_type=client_credentials&scope=openid+email&audience=$AUDIENCE" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    STATUS=$(curl -sk -o /dev/null -w '%{http_code}' \
        -H "Authorization: Bearer $TOKEN" \
        "https://{{domain}}/bookinfo-ingress2/bookinfo-productpage2")
    echo "HTTP $STATUS"
    if [ "$STATUS" = "200" ]; then echo "✓ PASS"; else echo "✗ FAIL (expected 200)"; fi

# run all tests
test-all client_id client_secret:
    just -f {{justfile()}} test-browser-auth
    just -f {{justfile()}} test-jwt-notoken
    just -f {{justfile()}} test-jwt {{client_id}} {{client_secret}}

# ============================================================
# Debugging
# ============================================================

logs-hydra:
    kubectl -n {{model-iam}} logs hydra-0 -c hydra --tail=100 | grep -v health | grep -v pebble

logs-oauth2-proxy:
    kubectl -n {{model-bookinfo}} logs oauth2-proxy-0 -c oauth2-proxy --tail=50 | grep -v ready | grep -v pebble

logs-ingress1:
    kubectl -n {{model-bookinfo}} logs -l gateway.networking.k8s.io/gateway-name=ingress1 --tail=50

logs-ingress2:
    kubectl -n {{model-bookinfo}} logs -l gateway.networking.k8s.io/gateway-name=ingress2 --tail=50

show-ingress-urls:
    #!/usr/bin/env bash
    echo "--- Traefik routes ---"
    kubectl -n {{model-iam}} exec traefik-0 -c traefik -- traefik-show-routes 2>/dev/null \
        || echo "(traefik-show-routes not available, check traefik dashboard)"
    echo ""
    echo "--- Gateway resources ---"
    kubectl -n {{model-bookinfo}} get gateway -o wide 2>/dev/null || true
