output "app_name" {
  value = juju_application.tailscale_beacon.name
}

output "provides" {
  value = {
    ingress = "ingress"
  }
}

output "requires" {
  value = {}
}
