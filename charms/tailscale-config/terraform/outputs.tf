output "app_name" {
  value = juju_application.tailscale_config.name
}

output "provides" {
  value = {
    tailscale_credentials = "tailscale-credentials"
  }
}

output "requires" {
  value = {}
}
