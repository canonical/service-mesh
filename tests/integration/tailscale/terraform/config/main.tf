# Python creates/grants the root secret, configures its URI, and owns credential
# relations. Provider refreshes may record that URI, never the secret contents.
module "config" {
  source = "../../../../../charms/tailscale-config/terraform"

  model_uuid = var.model_uuid
  app_name   = var.app_name
  channel    = var.channel
  revision   = var.revision
  config     = var.config
}
