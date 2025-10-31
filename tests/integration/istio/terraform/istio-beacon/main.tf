data "juju_model" "istio_beacon_model" {
  name  = var.model
  owner = "admin"
}

module "istio_beacon" {
  source     = "git::https://github.com/canonical/istio-beacon-k8s-operator//terraform"
  model_uuid = data.juju_model.istio_beacon_model.uuid
  channel    = var.channel
  config     = var.config
}
