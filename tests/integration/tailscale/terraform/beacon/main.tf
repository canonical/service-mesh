# Python owns ingress relations so scenarios can change them without state drift.
module "beacon" {
  source = "../../../../../charms/tailscale-beacon-k8s/terraform"

  model_uuid = var.model_uuid
  app_name   = var.app_name
  channel    = var.channel
  revision   = var.revision
  config     = var.config
}
