output "app_name" {
  description = "Name of the deployed Tailscale config application"
  value       = module.config.app_name
}

output "tailscale_credentials_endpoint" {
  description = "Endpoint providing scoped Tailscale credentials"
  value       = module.config.provides.tailscale_credentials
}
