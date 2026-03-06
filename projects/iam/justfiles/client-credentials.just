# Client credentials flow setup
# Requires: browser auth setup from setup.just already deployed and active

import 'setup.just'

# enable JWT bearer tokens on oauth2-proxy and create a client_credentials client in hydra
setup-client-credentials: enable-jwt-bearer-tokens create-m2m-client

# enable oauth2-proxy to accept Bearer JWTs via ext_authz
enable-jwt-bearer-tokens:
    juju config -m {{model-bookinfo}} oauth2-proxy enable_jwt_bearer_tokens=true

# get the oauth2-proxy client_id from the oauth relation with hydra
get-oauth2-proxy-client-id:
    #!/usr/bin/env bash
    juju show-unit -m {{model-bookinfo}} oauth2-proxy/0 --format yaml \
        | python3 -c "
    import sys, yaml
    data = yaml.safe_load(sys.stdin)['oauth2-proxy/0']
    for ri in data['relation-info']:
        if ri['endpoint'] == 'oauth':
            print(ri['application-data']['client_id'])
            break
    "

# create an OAuth2 client in Hydra with client_credentials grant type
# audience must match oauth2-proxy's client_id so oauth2-proxy accepts the JWT
create-m2m-client:
    #!/usr/bin/env bash
    AUDIENCE=$(just -f {{justfile()}} get-oauth2-proxy-client-id)
    kubectl -n {{model-iam}} exec hydra-0 -c hydra -- \
        hydra create oauth2-client \
        --endpoint http://localhost:4445 \
        --name "test-m2m-client" \
        --grant-type client_credentials \
        --response-type token \
        --scope openid \
        --audience "$AUDIENCE" \
        --access-token-strategy jwt \
        --format json

# list all OAuth2 clients in Hydra
list-clients:
    kubectl -n {{model-iam}} exec hydra-0 -c hydra -- \
        hydra list clients --endpoint http://localhost:4445 --format json

# delete a client by ID
delete-client id:
    kubectl -n {{model-iam}} exec hydra-0 -c hydra -- \
        hydra delete client {{id}} --endpoint http://localhost:4445

# get a token using client_credentials flow
get-token client_id client_secret:
    #!/usr/bin/env bash
    AUDIENCE=$(just -f {{justfile()}} get-oauth2-proxy-client-id)
    TOKEN_URL=$(juju show-unit -m {{model-bookinfo}} oauth2-proxy/0 --format yaml \
        | python3 -c "
    import sys, yaml
    data = yaml.safe_load(sys.stdin)['oauth2-proxy/0']
    for ri in data['relation-info']:
        if ri['endpoint'] == 'oauth':
            print(ri['application-data']['token_endpoint'])
            break
    ")
    curl -sk -X POST "$TOKEN_URL" \
        -u "{{client_id}}:{{client_secret}}" \
        -d "grant_type=client_credentials&scope=openid&audience=$AUDIENCE" \
        | python3 -m json.tool

# check what headers oauth2-proxy returns for a JWT
check-headers client_id client_secret:
    #!/usr/bin/env bash
    AUDIENCE=$(just -f {{justfile()}} get-oauth2-proxy-client-id)
    TOKEN_URL=$(juju show-unit -m {{model-bookinfo}} oauth2-proxy/0 --format yaml \
        | python3 -c "
    import sys, yaml
    data = yaml.safe_load(sys.stdin)['oauth2-proxy/0']
    for ri in data['relation-info']:
        if ri['endpoint'] == 'oauth':
            print(ri['application-data']['token_endpoint'])
            break
    ")
    TOKEN=$(curl -sk -X POST "$TOKEN_URL" \
        -u "{{client_id}}:{{client_secret}}" \
        -d "grant_type=client_credentials&scope=openid&audience=$AUDIENCE" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    kubectl -n {{model-bookinfo}} port-forward pod/oauth2-proxy-0 4180:4180 &
    PF_PID=$!
    sleep 2
    echo "--- ext_authz response headers ---"
    curl -s -D- -o /dev/null -H "Authorization: Bearer ${TOKEN}" http://localhost:4180/bookinfo-productpage
    kill $PF_PID 2>/dev/null
