output "app_name" {
  description = "Name of the deployed Tailscale beacon application"
  value       = module.beacon.app_name
}

output "ingress_endpoint" {
  description = "Endpoint exposing applications onto the tailnet"
  value       = module.beacon.provides.ingress
}
