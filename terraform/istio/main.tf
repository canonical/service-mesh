terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 0.14.0"
    }
  }
}

module "istio" {
  source = "git::https://github.com/canonical/istio-k8s-operator//terraform"

  model   = var.model
  channel = var.channel
}
