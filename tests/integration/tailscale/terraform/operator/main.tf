# Python owns credentials and dynamic relations. Provider refreshes may record
# a configured secret URI in state, but Terraform must never receive its contents.
module "operator" {
  source = "../../../../../charms/tailscale-k8s/terraform"

  model_uuid = var.model_uuid
  app_name   = var.app_name
  channel    = var.channel
  revision   = var.revision
  config     = var.config
}
