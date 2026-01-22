output "app_name" {
  description = "Name of the deployed istio-ingress application"
  value       = module.istio_ingress.app_name
}

output "ingress_endpoint" {
  description = "Ingress endpoint name"
  value       = module.istio_ingress.endpoints.ingress
}
