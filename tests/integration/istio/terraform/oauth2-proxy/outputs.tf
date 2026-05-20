output "app_name" {
  description = "Name of the deployed oauth2-proxy application"
  value       = module.oauth2_proxy.app_name
}

output "forward_auth_endpoint" {
  description = "Forward-auth endpoint name"
  value       = module.oauth2_proxy.provides.forward-auth
}
