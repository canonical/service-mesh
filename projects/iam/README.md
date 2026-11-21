# IAM

Dev setup for authenticated ingress using the Canonical Identity Platform
(Hydra, Kratos, Login UI) with Charmed Istio Ambient.

Deploys across 3 Juju models: istio-system, iam, bookinfo.

All commands assume you are in the `justfiles` directory:

```
cd justfiles
```

## Setup

```
just -f setup.just setup          # deploy everything
just -f setup.just teardown       # destroy all 3 models
just -f setup.just status         # status of all models
```

## User management

```
just -f setup.just create-user email=test@example.com
just -f setup.just reset-password email=test@example.com
```

## Client credentials

Extends the base setup for programmatic M2M access via Bearer JWTs.

```
just -f client-credentials.just setup-client-credentials
```

Enables JWT bearer tokens on oauth2-proxy and creates a client_credentials
client in Hydra. Save the client_id and client_secret from the output.

```
just -f client-credentials.just get-token <client_id> <client_secret>
just -f client-credentials.just check-headers <client_id> <client_secret>
just -f client-credentials.just list-clients
just -f client-credentials.just delete-client <id>
just -f client-credentials.just get-oauth2-proxy-client-id
```

`get-token` exchanges credentials for a JWT. `check-headers` port-forwards
to oauth2-proxy and shows the ext_authz response headers. `get-oauth2-proxy-client-id`
prints the audience value needed when creating m2m clients.

## Debugging

```
just -f setup.just logs-hydra
just -f setup.just logs-oauth2-proxy
just -f setup.just show-hydra
```

## Docs

- `docs/browser-auth-flow.md` - browser OAuth2 flow with mermaid sequence diagrams
- `docs/client-credentials-flow.md` - programmatic access via client_credentials grant
- `docs/request-authentication-findings.md` - how RequestAuthentication could work
  alongside ext_authz for custom header mapping
- [`ingress-chaining.md`](ingress-chaining.md) - multi-gateway setup with Traefik routing to two Istio ingress gateways (browser auth + JWT auth) via path-based routing
