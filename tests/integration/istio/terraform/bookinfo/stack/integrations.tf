# -------------- # Bookinfo microservice integrations --------------

resource "juju_integration" "productpage_details" {
  model_uuid = var.model_uuid

  application {
    name     = module.productpage.app_name
    endpoint = module.productpage.endpoints.details
  }

  application {
    name     = module.details.app_name
    endpoint = module.details.endpoints.details
  }
}

# -------------- # Service Mesh integrations (conditional) --------------

resource "juju_integration" "productpage_beacon" {
  count = var.beacon_app_name != null ? 1 : 0
  model_uuid = var.model_uuid

  application {
    name     = module.productpage.app_name
    endpoint = module.productpage.endpoints.service_mesh
  }

  application {
    name     = var.beacon_app_name
    endpoint = var.beacon_service_mesh_endpoint
  }
}

resource "juju_integration" "details_beacon" {
  count = var.beacon_app_name != null ? 1 : 0
  model_uuid = var.model_uuid

  application {
    name     = module.details.app_name
    endpoint = module.details.endpoints.service_mesh
  }

  application {
    name     = var.beacon_app_name
    endpoint = var.beacon_service_mesh_endpoint
  }
}
