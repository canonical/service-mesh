# IAM auth dev setup - 3 models: istio-system, iam, bookinfo

model-istio := "istio-system"
model-iam := "iam"
model-bookinfo := "bookinfo"

ch-postgresql := "14/stable"
ch-hydra := "latest/edge"
ch-kratos := "latest/edge"
ch-login-ui := "latest/edge"
ch-traefik := "latest/stable"
ch-istio-ingress := "dev/edge"
ch-oauth2-proxy := "latest/edge"
ch-istio-k8s := "dev/edge"
ch-bookinfo := "latest/stable"
ch-self-signed-certs := "latest/stable"

# idempotent helpers

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
    @juju wait-for application {{app}} -m {{model}} --query='status == "active"' --timeout 10m 2>/dev/null

# deploy everything
setup: deploy-istio deploy-iam wait-iam deploy-bookinfo create-offers consume-offers integrate-cross-model

wait-iam:
    just -f {{justfile()}} _wait-for {{model-iam}} hydra
    just -f {{justfile()}} _wait-for {{model-iam}} self-signed-certs


# istio-system model

deploy-istio:
    just -f {{justfile()}} _add-model {{model-istio}}
    just -f {{justfile()}} _deploy {{model-istio}} istio-k8s istio-k8s {{ch-istio-k8s}}

# tear down everything
teardown:
    juju destroy-model {{model-bookinfo}} --no-prompt --destroy-storage --force
    juju destroy-model {{model-iam}} --no-prompt --destroy-storage --force
    juju destroy-model {{model-istio}} --no-prompt --destroy-storage --force

# status of all models
status:
    @echo "--- {{model-istio}} ---"
    juju status -m {{model-istio}} --format short
    @echo "--- {{model-iam}} ---"
    juju status -m {{model-iam}} --format short
    @echo "--- {{model-bookinfo}} ---"
    juju status -m {{model-bookinfo}} --format short

# iam model

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
    # kratos needs dev mode for HTTP internally, hydra does NOT - its cookies break in dev mode over TLS
    juju config -m {{model-iam}} kratos dev=true

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
    # TLS on traefik - login-ui hardcodes https in normalise_url, so traefik must serve TLS
    just -f {{justfile()}} _integrate {{model-iam}} self-signed-certs:certificates traefik:certificates
    # CA cert so kratos and login-ui trust traefik's TLS
    just -f {{justfile()}} _integrate {{model-iam}} self-signed-certs:send-ca-cert kratos:receive-ca-cert
    just -f {{justfile()}} _integrate {{model-iam}} self-signed-certs:send-ca-cert login-ui:receive-ca-cert

# bookinfo model

deploy-bookinfo: deploy-bookinfo-charms configure-bookinfo integrate-bookinfo

configure-bookinfo:
    # oauth2-proxy charm bug: receive-ca-cert data is ignored, cert never reaches the workload.
    # dev mode sets SSL_INSECURE_SKIP_VERIFY so OIDC discovery works against traefik's self-signed TLS.
    juju config -m {{model-bookinfo}} oauth2-proxy dev=true

deploy-bookinfo-charms:
    just -f {{justfile()}} _add-model {{model-bookinfo}}
    just -f {{justfile()}} _deploy {{model-bookinfo}} bookinfo-productpage-k8s productpage {{ch-bookinfo}}
    just -f {{justfile()}} _deploy {{model-bookinfo}} bookinfo-details-k8s details {{ch-bookinfo}}
    just -f {{justfile()}} _deploy {{model-bookinfo}} istio-ingress-k8s ingress {{ch-istio-ingress}}
    just -f {{justfile()}} _deploy {{model-bookinfo}} oauth2-proxy-k8s oauth2-proxy {{ch-oauth2-proxy}}
    just -f {{justfile()}} _deploy {{model-bookinfo}} self-signed-certificates self-signed-certs {{ch-self-signed-certs}}

integrate-bookinfo:
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:forward-auth ingress:forward-auth
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:ingress ingress:ingress-unauthenticated
    just -f {{justfile()}} _integrate {{model-bookinfo}} productpage:ingress ingress:ingress
    just -f {{justfile()}} _integrate {{model-bookinfo}} productpage:details details:details
    # TLS on istio ingress - redirect_uri must be https, otherwise hydra CSRF cookies fail
    just -f {{justfile()}} _integrate {{model-bookinfo}} self-signed-certs:certificates ingress:certificates

# cross-model

create-offers:
    just -f {{justfile()}} _offer {{model-istio}}.istio-k8s:istio-ingress-config istio-ingress-config
    just -f {{justfile()}} _offer {{model-iam}}.hydra:oauth hydra-oauth
    just -f {{justfile()}} _offer {{model-iam}}.self-signed-certs:send-ca-cert iam-ca-cert

consume-offers:
    just -f {{justfile()}} _consume admin/{{model-istio}}.istio-ingress-config {{model-bookinfo}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.hydra-oauth {{model-bookinfo}}
    just -f {{justfile()}} _consume admin/{{model-iam}}.iam-ca-cert {{model-bookinfo}}

integrate-cross-model:
    just -f {{justfile()}} _integrate {{model-bookinfo}} ingress:istio-ingress-config istio-ingress-config
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:oauth hydra-oauth
    # CA cert so oauth2-proxy trusts traefik's TLS for OIDC discovery
    just -f {{justfile()}} _integrate {{model-bookinfo}} oauth2-proxy:receive-ca-cert iam-ca-cert

# user management

create-user email username="admin":
    juju run -m {{model-iam}} kratos/0 create-admin-account username={{username}} email={{email}}

reset-password email:
    juju run -m {{model-iam}} kratos/0 reset-password email={{email}}

# debugging

logs-hydra:
    kubectl -n {{model-iam}} logs hydra-0 -c hydra --tail=100 | grep -v health | grep -v pebble

logs-oauth2-proxy:
    kubectl -n {{model-bookinfo}} logs oauth2-proxy-0 -c oauth2-proxy --tail=50 | grep -v ready | grep -v pebble

show-hydra:
    juju show-unit -m {{model-iam}} hydra/0
