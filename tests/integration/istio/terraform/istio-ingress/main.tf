data "juju_model" "istio_ingress_model" {
  name  = var.model
  owner = "admin"
}

module "istio_ingress" {
  source     = "git::https://github.com/canonical/istio-ingress-k8s-operator//terraform"
  model_uuid = data.juju_model.istio_ingress_model.uuid
  channel    = var.channel
  config     = var.config
}
