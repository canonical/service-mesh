output "app_name" {
  value = juju_application.tailscale.name
}

output "provides" {
  # The tailscale-k8s charm does not currently expose any provider endpoints.
  value = {}
}

output "requires" {
  # The tailscale-k8s charm does not currently expose any requirer endpoints.
  # A `tailscale-credentials` requirer relation is planned; see charmcraft.yaml.
  value = {}
}
