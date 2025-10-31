terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 1.0"
    }
  }
}

data "juju_model" "bookinfo_model" {
  name  = var.model
  owner = "admin"
}

module "bookinfo_stack" {
  source = "./stack"

  model_uuid                   = data.juju_model.bookinfo_model.uuid
  channel                      = var.channel
  beacon_app_name              = var.beacon_app_name
  beacon_service_mesh_endpoint = var.beacon_service_mesh_endpoint
}
