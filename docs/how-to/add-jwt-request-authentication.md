# Add JWT request authentication to your charm

This guide explains how to add JWT request authentication to your charm using the [`istio-request-auth`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/interfaces/istio-request-auth) interface library. This relation lets your charm tell the Istio ingress gateway which JWT issuers to trust and how to map JWT claims onto request headers, so that authenticated requests reach your workload with identity information it can use.

## What is the `istio-request-auth` relation for?

The [`istio-ingress-k8s`](https://charmhub.io/istio-ingress-k8s) charm wraps an Istio [Kubernetes Gateway](https://gateway-api.sigs.k8s.io/). Istio can natively validate a JSON Web Token (JWT) carried on a request against a trusted issuer using a [`RequestAuthentication`](https://istio.io/latest/docs/reference/config/security/request_authentication/) resource. When a request carries a valid JWT, Istio validates it at the gateway and can copy claims from the token (such as `email` or `sub`) into request headers before forwarding the request to your workload.

This is distinct from, but complementary to, the [`forward-auth`](./authenticated-ingress-with-the-canonical-identity-platform.md) relation used with `oauth2-proxy`. `forward-auth` handles the interactive browser login flow (external authorization), while `istio-request-auth` handles native JWT validation and claim-to-header mapping. The two work together: a browser request is authenticated by `oauth2-proxy`, which injects a JWT, and Istio then validates that JWT and maps its claims to headers.

The motivating use case is an application that needs a user identity in a specific header. For example, the Kubeflow dashboard expects the authenticated user's email in a `kubeflow-userid` header. Only your charm knows which claims it needs and which headers to map them to, so your charm publishes those mappings to the gateway over the `istio-request-auth` relation. The gateway then creates the `RequestAuthentication` resource on your behalf.

For more on how authorization works in a charmed service mesh, see [Traffic authorization](../explanation/traffic-authorization.md).

## Add the required relation to `charmcraft.yaml`

Add the `istio-request-auth` relation to your charm's `charmcraft.yaml`:

```yaml
requires:
  istio-request-auth:
    interface: istio_request_auth
    limit: 1
    description: |
      Publish JWT authentication rules to the Istio ingress gateway. The gateway
      creates a RequestAuthentication resource from these rules to validate JWTs
      and map token claims to request headers.
```

## Add the library dependency

The [`istio-request-auth`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/interfaces/istio-request-auth) interface library is distributed as a Python package. Add it to your charm's `pyproject.toml`:

```text
charmlibs-interfaces-istio-request-auth
```

## Use `IstioRequestAuthRequirer` in your charm

Instantiate the requirer in your charm's `__init__` and publish your JWT rules whenever your configuration or relations change.

### Instantiate the requirer

```python
from charmlibs.interfaces.istio_request_auth import (
    ClaimToHeader,
    FromHeader,
    IstioRequestAuthRequirer,
    JWTRule,
)


class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.request_auth = IstioRequestAuthRequirer(self, relation_name="istio-request-auth")
        self.framework.observe(
            self.on["istio-request-auth"].relation_changed, self._publish_jwt_rules
        )
        self.framework.observe(self.on.config_changed, self._publish_jwt_rules)
```

### Define and publish JWT rules

Each [`JWTRule`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/interfaces/istio-request-auth) describes one issuer to trust and how to handle tokens from it. Call `publish_data` with the rules you want the gateway to enforce:

```python
    def _publish_jwt_rules(self, _):
        self.request_auth.publish_data(
            [
                JWTRule(
                    issuer="https://accounts.example.com",
                    jwks_uri="https://accounts.example.com/jwks",
                    forward_original_token=True,
                    claim_to_headers=[
                        ClaimToHeader(header="kubeflow-userid", claim="email"),
                    ],
                    from_headers=[
                        FromHeader(name="Authorization", prefix="Bearer "),
                    ],
                )
            ]
        )
```

The fields of a `JWTRule` mirror the [Istio `JWTRule`](https://istio.io/latest/docs/reference/config/security/request_authentication/#JWTRule) entry:

* `issuer`: the issuer URL that the JWT must be issued by (required).
* `jwks_uri`: the JSON Web Key Set endpoint used to validate the token signature.
* `audiences`: an optional list of audiences the token must be intended for.
* `forward_original_token`: whether to keep the original token on the request forwarded to your workload.
* `claim_to_headers`: a list of [`ClaimToHeader`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/interfaces/istio-request-auth) mappings, each copying a JWT `claim` into the named `header`.
* `from_headers`: a list of [`FromHeader`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/interfaces/istio-request-auth) locations describing where to extract the JWT from, each with a header `name` and optional `prefix`.

```{note}
`publish_data` only writes to the relation databag when the unit is the leader. You can call it unconditionally; the library skips the write on non-leader units.
```

## Integrate your charm with the ingress

Once your charm supports the relation, deploy it alongside `istio-ingress-k8s` and integrate the two:

```bash
juju integrate my-charm:istio-request-auth ingress:istio-request-auth
```

When the relation is established and your charm has published valid JWT rules, the ingress charm creates two Kubernetes resources in its own namespace, both targeting its gateway:

* a `RequestAuthentication` resource (named `request-auth-<your-app>-<ingress-app>`) built from your published rules, and
* a `DENY` `AuthorizationPolicy` (named `deny-without-jwt-<ingress-app>`) that rejects any request without a validated JWT principal, ensuring fail-closed behaviour.

When `forward-auth` is also active on the same gateway, the `DENY` policy is scoped to requests carrying a `Bearer` token so that non-`Bearer` requests continue to flow through the external authorization stack.

## Verify the resources

After the charms settle to `active/idle`, you can inspect the resources the gateway created in its model's namespace:

```bash
kubectl get requestauthentication -n <ingress-model>
kubectl get authorizationpolicy -n <ingress-model>
```

You should see the `request-auth-<your-app>-<ingress-app>` and `deny-without-jwt-<ingress-app>` resources. Inspect the `RequestAuthentication` to confirm your issuer and claim-to-header mappings were applied:

```bash
kubectl get requestauthentication request-auth-<your-app>-<ingress-app> -n <ingress-model> -o yaml
```

## Further reading

* [Traffic authorization](../explanation/traffic-authorization.md)
* [Authenticated ingress with the Canonical Identity Platform](./authenticated-ingress-with-the-canonical-identity-platform.md)
* [`istio-request-auth` library reference](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/interfaces/istio-request-auth)
* [Istio `RequestAuthentication` reference](https://istio.io/latest/docs/reference/config/security/request_authentication/)
