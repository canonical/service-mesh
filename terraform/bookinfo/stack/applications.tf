# -------------- # Bookinfo Applications --------------

module "productpage" {
  source             = "git::https://github.com/adhityaravi/bookinfo-operators//charms/bookinfo-productpage-k8s/terraform"
  app_name           = var.productpage.app_name
  channel            = var.channel
  config             = var.productpage.config
  constraints        = var.productpage.constraints
  model              = var.model
  revision           = var.productpage.revision
  storage_directives = var.productpage.storage_directives
  units              = var.productpage.units
}

module "details" {
  source             = "git::https://github.com/adhityaravi/bookinfo-operators//charms/bookinfo-details-k8s/terraform"
  app_name           = var.details.app_name
  channel            = var.channel
  config             = var.details.config
  constraints        = var.details.constraints
  model              = var.model
  revision           = var.details.revision
  storage_directives = var.details.storage_directives
  units              = var.details.units
}
