# Browser Auth Flow

How a browser request to a protected app (bookinfo productpage) gets authenticated
through the Charmed Istio Ambient + IAM stack.

Reference setup: `justfiles/setup.just`

## Components

| Component | Model | Role |
|---|---|---|
| istio-k8s | istio-system | mesh control plane, holds ext_authz config |
| ingress (istio-ingress-k8s) | bookinfo | gateway, enforces ext_authz via AuthorizationPolicy |
| oauth2-proxy | bookinfo | ext_authz decision maker, drives OAuth2 flow |
| traefik | iam | TLS-terminating reverse proxy for IAM services |
| hydra | iam | OAuth2/OIDC provider, issues tokens |
| login-ui | iam | web frontend for login/consent, brokers Hydra + Kratos |
| kratos | iam | identity store, validates credentials |

## Why Traefik?

The IAM charms (hydra, kratos, login-ui) dropped support for the generic `ingress`
interface (IPA) in mid-2025 and now only expose a `public-route` relation using the
`traefik_route` interface. This means they can only be fronted by Traefik, not by
Istio ingress or any other ingress provider directly.

Until the IAM charms either revive the generic ingress interface or add support for
`istio-ingress-route`, Traefik is a required component in this setup.

## Step 1: Unauthenticated request hits ext_authz

The browser hits productpage. Envoy intercepts and asks oauth2-proxy
if the request is allowed. No session cookie exists, so oauth2-proxy
redirects to Hydra.

```mermaid
sequenceDiagram
    actor Browser
    participant Ingress as ingress<br/>istio-ingress-k8s
    participant OAuth2 as oauth2-proxy
    participant Hydra

    Browser->>Ingress: GET https://INGRESS_IP/bookinfo-productpage
    Note over Ingress: AuthorizationPolicy CUSTOM<br/>triggers ext_authz check
    Ingress->>OAuth2: ext_authz: is this request allowed?
    OAuth2->>OAuth2: no _oauth2_proxy session cookie
    OAuth2-->>Ingress: 302 redirect to Hydra
    Ingress-->>Browser: 302 Location: https://TRAEFIK_IP/oauth2/auth?client_id=...&redirect_uri=...&scope=openid email profile
```

The ext_authz provider is configured through two relations:
- `oauth2-proxy:forward-auth` -> `ingress:forward-auth` passes the decisions address
- `ingress:istio-ingress-config` -> `istio-k8s:istio-ingress-config` registers the provider in mesh config

The `ingress` endpoint on istio-ingress is the authenticated route.
The `ingress-unauthenticated` endpoint bypasses ext_authz entirely.
oauth2-proxy's own callback uses this to avoid an infinite auth loop.

## Step 2: Hydra starts the login flow

Hydra receives the OAuth2 authorization request. It doesn't authenticate
users itself, it delegates to Login UI via a login challenge.

```mermaid
sequenceDiagram
    actor Browser
    participant Traefik
    participant Hydra

    Browser->>Traefik: GET /oauth2/auth?client_id=...&scope=...
    Traefik->>Hydra: forward, TLS terminated
    Hydra->>Hydra: create login request<br/>generate CSRF token, store in DB
    Hydra-->>Browser: 302 -> /ui/login?login_challenge=abc123<br/>Set-Cookie: ory_hydra_login_csrf [Secure, SameSite=None]
```

The CSRF cookie ties this browser session to the login request in the DB.
Hydra must NOT run in dev mode over TLS. Dev mode omits the `Secure` flag,
and browsers reject `SameSite=None` cookies without `Secure`.

Hydra knows the login URL from the `ui-endpoint-info` relation.
Login UI advertises `https://TRAEFIK_IP/ui/login`. The HTTPS is
hardcoded by `normalise_url` in the login-ui charm, which is why
Traefik must have TLS.

## Step 3: Login UI authenticates the user via Kratos

Login UI receives the login challenge, checks with Hydra what's being
requested, then runs the user through Kratos authentication.

```mermaid
sequenceDiagram
    actor Browser
    participant Traefik
    participant LoginUI as login-ui
    participant Hydra
    participant Kratos

    Browser->>Traefik: GET /ui/login?login_challenge=abc123
    Traefik->>LoginUI: forward

    LoginUI->>Hydra: GET /admin/.../requests/login?login_challenge=abc123
    Hydra-->>LoginUI: client info, requested scopes

    LoginUI->>Kratos: init self-service login flow
    Kratos-->>LoginUI: flow ID
    LoginUI-->>Browser: render login page

    Browser->>Traefik: POST email + password
    Traefik->>Kratos: submit to self-service login
    Kratos->>Kratos: validate credentials against postgresql
    Kratos-->>LoginUI: identity confirmed
```

If `enforce_mfa=True` on Kratos (the default), an extra round trip happens:

```mermaid
sequenceDiagram
    actor Browser
    participant Traefik
    participant LoginUI as login-ui
    participant Kratos

    LoginUI-->>Browser: render TOTP page
    Browser->>Traefik: POST TOTP code
    Traefik->>Kratos: validate second factor
    Kratos-->>LoginUI: MFA passed
```

## Step 4: Login accepted, CSRF check, consent

Login UI tells Hydra the user is authenticated. The browser is redirected
back to Hydra, which validates the CSRF cookie and moves to consent.

```mermaid
sequenceDiagram
    actor Browser
    participant Traefik
    participant LoginUI as login-ui
    participant Hydra

    LoginUI->>Hydra: PUT /admin/.../login/accept<br/>subject=user-uuid, remember=true
    Hydra-->>LoginUI: redirect_to: /oauth2/auth?login_verifier=xyz
    LoginUI-->>Browser: 302 -> /oauth2/auth?login_verifier=xyz

    Browser->>Traefik: GET /oauth2/auth?login_verifier=xyz<br/>Cookie: ory_hydra_login_csrf=...
    Traefik->>Hydra: forward
    Hydra->>Hydra: CSRF check: cookie == DB value ✓
    Hydra-->>Browser: 302 -> /ui/consent?consent_challenge=def456

    Browser->>Traefik: GET /ui/consent?consent_challenge=def456
    Traefik->>LoginUI: forward
    LoginUI->>Hydra: PUT /admin/.../consent/accept<br/>grant_scope: openid, email, profile
    Hydra->>Hydra: generate authorization code
    Hydra-->>LoginUI: redirect_to: callback?code=AUTH_CODE
    LoginUI-->>Browser: 302 -> https://INGRESS_IP/.../oauth2/callback?code=AUTH_CODE
```

The consent step asks "does the user allow this client to access their data?"
In this setup, login-ui auto-accepts without prompting the user.

## Step 5: Token exchange and session

oauth2-proxy receives the authorization code, exchanges it for tokens,
and sets a session cookie.

```mermaid
sequenceDiagram
    actor Browser
    participant Ingress as ingress
    participant OAuth2 as oauth2-proxy
    participant Traefik
    participant Hydra

    Browser->>Ingress: GET /oauth2/callback?code=AUTH_CODE<br/>via ingress-unauthenticated, no ext_authz
    Ingress->>OAuth2: forward

    OAuth2->>Traefik: POST /oauth2/token<br/>client_id + client_secret + AUTH_CODE
    Traefik->>Hydra: forward
    Hydra-->>OAuth2: id_token + access_token + refresh_token

    OAuth2->>OAuth2: parse id_token, extract email and subject
    OAuth2-->>Browser: 302 -> /bookinfo-productpage<br/>Set-Cookie: _oauth2_proxy
```

oauth2-proxy knows Hydra's token endpoint and its own client credentials
from the cross-model `oauth` relation. Hydra registered the OAuth2 client
when the relation was established. The only client in this setup is
oauth2-proxy itself. Users are not OAuth2 clients, they exist in Kratos.

The three tokens:
- **id_token** (JWT): who is the user. Contains email, subject. This is what oauth2-proxy reads to set headers.
- **access_token** (JWT): what the client can do. Contains granted scopes. Used for API calls on behalf of the user.
- **refresh_token** (opaque): how to get fresh tokens without re-authenticating. Keeps the session alive long-term.

## Step 6: Authenticated request

The browser retries with the session cookie. oauth2-proxy validates it
and tells Envoy to allow the request, setting identity headers.

```mermaid
sequenceDiagram
    actor Browser
    participant Ingress as ingress
    participant OAuth2 as oauth2-proxy
    participant App as productpage

    Browser->>Ingress: GET /bookinfo-productpage<br/>Cookie: _oauth2_proxy=...
    Ingress->>OAuth2: ext_authz check
    OAuth2->>OAuth2: valid session ✓
    OAuth2-->>Ingress: 200 allow<br/>X-Forwarded-Email: test@example.com
    Note over Ingress: propagates headers via<br/>headersToUpstreamOnAllow
    Ingress->>App: GET /bookinfo-productpage + identity headers
    App-->>Browser: productpage HTML
```

The headers oauth2-proxy sets are propagated upstream because the
`forward-auth` relation passes them to istio-ingress, which passes
them to istio-k8s via `istio-ingress-config`. istio-k8s writes them
into the mesh config as `headersToUpstreamOnAllow` on the ext_authz provider.
