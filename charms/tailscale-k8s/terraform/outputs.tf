output "app_name" {
  value = juju_application.tailscale.name
}

output "provides" {
  # The tailscale-k8s charm does not currently expose any provider endpoints.
  value = {}
}

output "requires" {
  value = {
    tailscale_credentials = "tailscale-credentials"
  }
}
