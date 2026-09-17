module "productpage" {
  source   = "../../../../../charms/bookinfo-productpage-k8s/terraform"
  for_each = var.productpages

  model_uuid = var.model_uuid
  app_name   = each.key
  channel    = var.channel
  units      = each.value.units
  config     = each.value.config
}

module "details" {
  source = "../../../../../charms/bookinfo-details-k8s/terraform"

  model_uuid = var.model_uuid
  app_name   = "details"
  channel    = var.channel
}

# Only static Bookinfo relations belong in state; Python owns ingress relations.
resource "juju_integration" "productpage_details" {
  for_each   = var.productpages
  model_uuid = var.model_uuid

  application {
    name     = module.productpage[each.key].app_name
    endpoint = module.productpage[each.key].endpoints.details
  }

  application {
    name     = module.details.app_name
    endpoint = module.details.endpoints.details
  }
}
