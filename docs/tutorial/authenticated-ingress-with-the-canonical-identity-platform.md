# Authenticated Ingress with the Canonical Identity Platform

## Introduction

This tutorial demonstrates how to use the Canonical Identity Platform to add authentication to an Istio Ingress.

## Prerequisites

Before starting this tutorial, ensure you have:

- Completed the [Get started with Charmed Istio service mesh](./get-started-with-the-charmed-istio-mesh.md) tutorial, which will give you a deployment of Istio and the sample Bookinfo application ingressed through an istio-ingress
- Deployed the Canonical Identity Platform following [this tutorial](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial).  Specifically , you must complete [Deploy the Identity Platform](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial#p-27742-deploy-the-identity-platform) and then [Set up a user with the built-in identity provider](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial#p-27742-use-the-built-in-identity-provider)

````{warning}
Until [this issue](https://github.com/canonical/iam-bundle-integration/issues/66) is resolved, the Identity tutorial deploys an older version of [self-signed-certificates](https://github.com/canonical/self-signed-certificates-operator) that is incompatible with the [oauth2-proxy](https://github.com/canonical/oauth2-proxy-k8s-operator) charm used below.  

To fix this, before doing `terraform apply` in the Identity Platform tutorial, edit the `certificates` variable in `examples/tutorial/variables.tf` to use a newer version:

```
variable "certificates" {
  description = "The configurations of the self-signed-certificates application."
  type = object({
    units   = optional(number, 1)
    trust   = optional(bool, true)
    config  = optional(map(string), {})
    channel = optional(string, "1/stable")     # <-- EDIT: previously "latest/stable"
    base    = optional(string, "ubuntu@24.04") # <-- EDIT: previously "ubuntu@22.04"
  })
  default = {}
}
```

and the `traefik` variable to:

```
variable "traefik" {
  description = "The configurations of the Traefik application."
  type = object({
    units   = optional(number, 1)
    trust   = optional(bool, true)
    config  = optional(map(string), {})
    channel = optional(string, "latest/edge") # <-- EDIT: previously "latest/stable"
    base    = optional(string, "ubuntu@20.04")
  })
  default = {}
}
```

````

Applying This should yield a starting point similar to:

````{dropdown} juju status --relations --model iam
```
Model  Controller      Cloud/Region              Version  SLA          Timestamp
iam    local-microk8s  local-microk8s/localhost  3.6.8    unsupported  16:50:58-04:00

SAAS        Status  Store  URL
ingress     active  local  admin/core.ingress
postgresql  active  local  admin/core.postgresql

App       Version  Status  Scale  Charm                                Channel        Rev  Address         Exposed  Message
hydra     v2.3.0   active      1  hydra                                latest/stable  362  10.152.183.168  no            
kratos    v1.3.1   active      1  kratos                               latest/stable  527  10.152.183.136  no       
login-ui  0.20.0   active      1  identity-platform-login-ui-operator  latest/stable  166  10.152.183.37   no        

Unit         Workload  Agent  Address       Ports  Message
hydra/0*     active    idle   10.1.253.238                
kratos/0*    active    idle   10.1.253.245         
login-ui/0*  active    idle   10.1.253.241             

Offer              Application  Charm   Rev  Connected  Endpoint     Interface    Role
kratos-info-offer  kratos       kratos  527  0/0        kratos-info  kratos_info  provider
oauth-offer        hydra        hydra   362  0/0        oauth        oauth        provider

Integration provider                 Requirer                             Interface                         Type     Message
hydra:hydra                          hydra:hydra                          hydra_peers                       peer     
hydra:hydra-endpoint-info            kratos:hydra-endpoint-info           hydra_endpoints                   regular  
hydra:hydra-endpoint-info            login-ui:hydra-endpoint-info         hydra_endpoints                   regular  
ingress:ingress                      hydra:public-ingress                 ingress                           regular  
ingress:ingress                      kratos:public-ingress                ingress                           regular  
ingress:ingress                      login-ui:ingress                     ingress                           regular  
kratos:kratos-info                   login-ui:kratos-info                 kratos_info                       regular  
kratos:kratos-peers                  kratos:kratos-peers                  kratos-peers                      peer     
login-ui:identity-platform-login-ui  login-ui:identity-platform-login-ui  identity_platform_login_ui_peers  peer     
login-ui:ui-endpoint-info            hydra:ui-endpoint-info               login_ui_endpoints                regular  
login-ui:ui-endpoint-info            kratos:ui-endpoint-info              login_ui_endpoints                regular  
postgresql:database                  hydra:pg-database                    postgresql_client                 regular  
postgresql:database                  kratos:pg-database                   postgresql_client                 regular
```
````

````{dropdown} juju status --relations --model core
```
Model  Controller      Cloud/Region              Version  SLA          Timestamp
core   local-microk8s  local-microk8s/localhost  3.6.8    unsupported  16:51:56-04:00

App                       Version  Status  Scale  Charm                     Channel        Rev  Address         Exposed  Message
postgresql-k8s            14.15    active      1  postgresql-k8s            14/stable      495  10.152.183.109  no       
self-signed-certificates           active      1  self-signed-certificates  1/stable       317  10.152.183.149  no        
traefik-public            2.11.0   active      1  traefik-k8s               latest/edge    242  10.152.183.234  no       Serving at 10.64.140.44

Unit                         Workload  Agent  Address       Ports  Message
postgresql-k8s/0*            active    idle   10.1.253.243         Primary
self-signed-certificates/0*  active    idle   10.1.253.237         
traefik-public/0*            active    idle   10.1.253.244         Serving at 10.64.140.44

Offer          Application               Charm                     Rev  Connected  Endpoint       Interface             Role
ingress        traefik-public            traefik-k8s               236  3/3        ingress        ingress               provider
postgresql     postgresql-k8s            postgresql-k8s            495  2/2        database       postgresql_client     provider
send-ca-cert   self-signed-certificates  self-signed-certificates  317  0/0        send-ca-cert   certificate_transfer  provider
traefik-route  traefik-public            traefik-k8s               236  0/0        traefik-route  traefik_route         provider

Integration provider                   Requirer                       Interface         Type     Message
postgresql-k8s:database-peers          postgresql-k8s:database-peers  postgresql_peers  peer     
postgresql-k8s:restart                 postgresql-k8s:restart         rolling_op        peer     
postgresql-k8s:upgrade                 postgresql-k8s:upgrade         upgrade           peer     
self-signed-certificates:certificates  traefik-public:certificates    tls-certificates  regular  
traefik-public:peers                   traefik-public:peers           traefik_peers     peer
```
````

````{dropdown} juju status --relations --model istio-system
```
Model         Controller      Cloud/Region              Version  SLA          Timestamp
istio-system  local-microk8s  local-microk8s/localhost  3.6.8    unsupported  16:52:40-04:00

App                Version  Status  Scale  Charm              Channel  Rev  Address        Exposed  Message
istio-ingress-k8s           active      1  istio-ingress-k8s  2/edge    43  10.152.183.28  no       Serving at 10.64.140.43
istio-k8s                   active      1  istio-k8s          2/edge    38  10.152.183.75  no            

Unit                  Workload  Agent  Address       Ports  Message
istio-ingress-k8s/0*  active    idle   10.1.253.202         Serving at 10.64.140.43
istio-k8s/0*          active    idle   10.1.253.201             

Offer              Application        Charm              Rev  Connected  Endpoint                 Interface  Role
istio-ingress-k8s  istio-ingress-k8s  istio-ingress-k8s  43   1/1        ingress                  ingress    provider
                                                                         ingress-unauthenticated  ingress    provider

Integration provider     Requirer                 Interface                Type  Message
istio-ingress-k8s:peers  istio-ingress-k8s:peers  istio_ingress_k8s_peers  peer  
istio-k8s:peers          istio-k8s:peers          istio_k8s_peers          peer
```
````

````{dropdown} juju status --relations --model bookinfo
```
Model     Controller      Cloud/Region              Version  SLA          Timestamp
bookinfo  local-microk8s  local-microk8s/localhost  3.6.8    unsupported  16:53:08-04:00

SAAS               Status  Store           URL
istio-ingress-k8s  active  local-microk8s  admin/istio-system.istio-ingress-k8s

App                       Version  Status  Scale  Charm                     Channel        Rev  Address         Exposed  Message
bookinfo-details-k8s               active      1  bookinfo-details-k8s      latest/stable    1  10.152.183.173  no       Ready
bookinfo-productpage-k8s           active      1  bookinfo-productpage-k8s  latest/stable    1  10.152.183.141  no       Ready with 2 backend services
bookinfo-reviews-k8s               active      1  bookinfo-reviews-k8s      latest/stable    1  10.152.183.145  no       Running version v1
istio-beacon-k8s                   active      1  istio-beacon-k8s          2/edge          38  10.152.183.105  no       

Unit                         Workload  Agent  Address       Ports  Message
bookinfo-details-k8s/0*      active    idle   10.1.253.247         Ready
bookinfo-productpage-k8s/0*  active    idle   10.1.253.248         Ready with 2 backend services
bookinfo-reviews-k8s/0*      active    idle   10.1.253.250         Running version v1
istio-beacon-k8s/0*          active    idle   10.1.253.246             

Integration provider           Requirer                               Interface               Type     Message
bookinfo-details-k8s:details   bookinfo-productpage-k8s:details       bookinfo-details        regular
bookinfo-reviews-k8s:reviews   bookinfo-productpage-k8s:reviews       bookinfo-reviews        regular
istio-beacon-k8s:peers         istio-beacon-k8s:peers                 istio_beacon_k8s_peers  peer
istio-beacon-k8s:service-mesh  bookinfo-details-k8s:service-mesh      service_mesh            regular
istio-beacon-k8s:service-mesh  bookinfo-productpage-k8s:service-mesh  service_mesh            regular
istio-beacon-k8s:service-mesh  bookinfo-reviews-k8s:service-mesh      service_mesh            regular
istio-ingress-k8s:ingress      bookinfo-productpage-k8s:ingress       ingress                 regular
```
````

From this stage, we can:
* browse to the Bookinfo application.  The URL is of the format `https://ISTIO_INGRESS_IP/bookinfo-bookinfo-productpage-k8s/productpage?u=normal` - use `juju run --model bookinfo bookinfo-productpage-k8s/leader get-url` to obtain the real URL.
* log into the Identity login page (login ui).  The URL is of the format `https://TRAEFIK_IP/iam-login-ui/ui/login` - use `juju run --model core traefik-public/leader show-proxied-endpoints` to obtain the real URL.

But browsing to the Bookinfo application did not require any authentication.  Next, we configure the Istio ingress to enforce authentication using the Identity Platform.

```{note}
Throughout this tutorial you will log into the identity platform a few times.  While it works in any browser configuration, using incognito sessions is recommended because its easy to close the session to reset any login cookies.  Its recommended that every time you try to log in fresh, you close your incognito session and start a new one.
```

## Configure the Identity Platform to use the Istio Ingress

### Configure the Istio Ingress to use TLS

The Identity Platform by default requires everything to be ingressed using https, but the [Get started with Charmed Istio](../tutorial/get-started-with-the-charmed-istio-mesh.md) tutorial used http.  To enable https, we can obtain certificates from the `self-signed-certificates` provided deployed in the Identity Platform tutorial by offering the certificate provider:

```bash
juju offer core.self-signed-certificates:certificates certificates
```

and using it in istio-ingress-k8s:

```bash
juju consume --model istio-system core.certificates
juju relate --model istio-system istio-ingress-k8s:certificates certificates
```

### Ingress the Identity Platform through Istio

Out of the box, the [Identity Platform tutorial](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial) uses [Traefik](https://github.com/canonical/traefik-k8s-operator) as an ingress.  To reconfigure that deployment to use our istio-ingress-k8s, consume the istio-ingress-k8s in the iam model:

```bash
juju consume --model iam istio-system.istio-ingress-k8s
```

Then change the ingress for all the Identity charms from Traefik to istio-ingress-k8s:

```bash
juju remove-relation --model iam hydra:public-ingress ingress
juju relate --model iam hydra:public-ingress istio-ingress-k8s:ingress-unauthenticated
juju remove-relation --model iam kratos:public-ingress ingress
juju relate --model iam kratos:public-ingress istio-ingress-k8s:ingress-unauthenticated
juju remove-relation --model iam login-ui:ingress ingress
juju relate --model iam login-ui:ingress istio-ingress-k8s:ingress-unauthenticated
```

Once this settles, we should be able to complete the login flow through the new ingress at `https://ISTIO_INGRESS_IP/iam-login-ui/ui/login`.

## Add Authentication to the Istio Ingress using the Identity Platform

By default, traffic is allowed through the Istio Ingress unauthenticated.  To add an authentication flow to that traffic, we connect the istio-ingress-k8s to istio-k8s to send additional configurations:

```bash
juju relate --model istio-system istio-ingress-k8s:istio-ingress-config istio-k8s:istio-ingress-config
```

deploy `oauth2-proxy`:

```bash
# Deploy oauth2-proxy and provide it with certificates used by other applications
juju deploy --model istio-system oauth2-proxy-k8s oauth2-proxy --channel=edge --trust
juju consume --model istio-system core.send-ca-cert
juju relate --model istio-system oauth2-proxy:receive-ca-cert send-ca-cert
juju relate --model istio-system oauth2-proxy:ingress istio-ingress-k8s:ingress-unauthenticated
```

and connect `oauth2-proxy` to the identity platform and istio-ingress:

```bash
juju consume --model istio-system iam.oauth-offer
juju relate --model istio-system oauth2-proxy:oauth oauth-offer

juju relate --model istio-system oauth2-proxy:forward-auth istio-ingress-k8s:forward-auth
```

Now when we browse to the Bookinfo application at `https://ISTIO_INGRESS_IP/bookinfo-bookinfo-productpage-k8s/productpage?u=normal`, we will be prompted first to log in through the Identity Platform.

## How to ingress some applications without authentication

istio-ingress-k8s offers two `ingress` integration endpoints, `ingress` and `ingress-unauthenticated`.  These both support the same interface, but differ in how they handle authentication:
 that differ in their authentication requirements:
* `ingress`: traffic ingressed using this integration **will always be authenticated *if authentication is configured on this istio-ingress-k8s***, otherwise traffic will be unauthenticated
* `ingress-unauthenticated`: traffic ingressed using this integration **will never be authenticated**

Typically, `ingress` is the integration you need.  But when some applications need to selectively be offered without authentication, use `ingress-unauthenticated` to keep them unrestricted.  

To try this out, deploy the [catalogue-k8s](https://github.com/canonical/catalogue-k8s-operator/) charm and ingress it without authentication:

```bash
juju deploy --model bookinfo catalogue-k8s catalogue
juju relate --model catalogue istio-ingress-k8s:ingress-unauthenticated
```

Now (in a new browser session, just so you know you're not already logged in) browse to Catalogue at `https://ISTIO_INGRESS_IP/bookinfo-catalogue`.  The application will be accessible without a login.

## Wrapping up

Congratulations!  You've successfully:

- configured istio-ingress-k8s to use the Identity Platform for authentication
- logged into the Identity Platform to access an application
- deployed an application that is never authenticated

## Teardown

To clean up the resources created in this tutorial, run:

```bash
juju destroy-model iam
juju destroy-model core
juju destroy-model istio-system
juju destroy-model bookinfo
```
