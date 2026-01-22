terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 1.0"
    }
  }
}

data "juju_model" "istio_model" {
  name  = var.model
  owner = "admin"
}

module "istio" {
  source = "git::https://github.com/canonical/istio-k8s-operator//terraform"

  model_uuid = data.juju_model.istio_model.uuid
  channel    = var.channel
  config     = var.config
}
