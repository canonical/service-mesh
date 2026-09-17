resource "juju_application" "tailscale_beacon" {
  name        = var.app_name
  config      = var.config
  constraints = var.constraints
  model_uuid  = var.model_uuid
  trust       = true
  units       = var.units

  charm {
    name     = "tailscale-beacon-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
