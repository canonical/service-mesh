output "app_name" {
  value = juju_application.istio_beacon.name
}

output "provides" {
  value = {
    service_mesh     = "service-mesh"
    metrics_endpoint = "metrics-endpoint"
  }
}

output "requires" {
  value = {
    charm_tracing = "charm-tracing"
  }
}
