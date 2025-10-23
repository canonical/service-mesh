output "app_name" {
  description = "Name of the deployed istio-beacon application"
  value       = module.istio_beacon.app_name
}

output "service_mesh_endpoint" {
  description = "Service mesh endpoint name"
  value       = module.istio_beacon.endpoints.service_mesh
}
