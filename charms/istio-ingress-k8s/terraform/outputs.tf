output "app_name" {
  value = juju_application.this_app.name
}

output "provides" {
  value = {
    ingress                             = "ingress"
    ingress-unauthenticated             = "ingress-unauthenticated"
    metrics-endpoint                    = "metrics-endpoint"
    istio-ingress-config                = "istio-ingress-config"
    istio-ingress-route                 = "istio-ingress-route"
    istio-ingress-route-unauthenticated = "istio-ingress-route-unauthenticated"
    gateway-metadata                    = "gateway-metadata"
    istio-request-auth                  = "istio-request-auth"
  }
}

output "requires" {
  value = {
    certificates     = "certificates"
    charm-tracing    = "charm-tracing"
    forward-auth     = "forward-auth"
    upstream-ingress = "upstream-ingress"
  }
}
