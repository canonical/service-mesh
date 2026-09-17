# Deploys the workloadless credential authority without elevated Juju trust.
resource "juju_application" "tailscale_config" {
  name        = var.app_name
  config      = var.config
  constraints = var.constraints
  model_uuid  = var.model_uuid
  units       = var.units

  charm {
    name     = "tailscale-config"
    channel  = var.channel
    revision = var.revision
  }
}
