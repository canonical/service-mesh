terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 0.14.0"
    }
  }
}

module "bookinfo_stack" {
  source = "./stack"

  model                        = var.model
  channel                      = var.channel
  beacon_app_name              = var.beacon_app_name
  beacon_service_mesh_endpoint = var.beacon_service_mesh_endpoint
}
