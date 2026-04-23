data "juju_model" "oauth2_proxy_model" {
  name  = var.model
  owner = "admin"
}

module "oauth2_proxy" {
  source   = "git::https://github.com/canonical/oauth2-proxy-k8s-operator//terraform"
  model    = data.juju_model.oauth2_proxy_model.uuid
  app_name = var.app_name
  channel  = var.channel
  config   = var.config
}
