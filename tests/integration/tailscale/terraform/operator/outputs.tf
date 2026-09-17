output "app_name" {
  description = "Name of the deployed Tailscale operator application"
  value       = module.operator.app_name
}

output "tailscale_credentials_endpoint" {
  description = "Endpoint receiving scoped Tailscale credentials"
  value       = module.operator.requires.tailscale_credentials
}
