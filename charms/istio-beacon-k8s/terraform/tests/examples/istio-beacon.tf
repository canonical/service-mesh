terraform {
  required_version = ">= 1.5"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 1.0"
    }
  }
}

provider "juju" {
  # These values can be set through environment variables:
  # JUJU_CONTROLLER_ADDRESSES - controller endpoint
  # JUJU_USERNAME - username
  # JUJU_PASSWORD - password
  # JUJU_CA_CERT - CA certificate

  # Or you can specify them explicitly:
  # controller_addresses = "10.0.0.1:17070"
  # username = "admin"
  # password = "your-password"
  # ca_certificate = file("~/juju-ca-cert.crt")
}

# Create a model for testing
resource "juju_model" "istio_beacon_test" {
  name = "istio-beacon-test"

  # Specify your cloud/substrate
  # For example, for microk8s:
  # cloud {
  #   name = "microk8s"
  # }

  # For other Kubernetes clouds, adjust accordingly
}

# Deploy Istio using the istio-k8s-operator module
# module "istio" {
#   source   = "git::https://github.com/canonical/istio-k8s-operator//terraform"
#   model    = juju_model.istio_beacon_test.name
#   channel  = "2/edge"
#   app_name = "istio"
#   units    = 1
# }

# Deploy Istio Beacon using the module (depends on Istio being deployed first)
module "istio_beacon" {
  source = "../.."

  # Required: reference to the model
  model_uuid = juju_model.istio_beacon_test.uuid

  # Required: specify the channel
  channel = "2/edge"

  # Optional: customize the deployment
  app_name = "istio-beacon"
  units    = 1

  # Optional: charm configuration
  config = {
    # Automatically create Istio authorization policies (default: true)
    manage-authorization-policies = true

    # Add entire model to the service mesh (default: false)
    model-on-mesh = false

    # Timeout for waypoint deployment readiness in seconds (default: 100)
    ready-timeout = 100
  }

  # Optional: constraints
  constraints = "arch=amd64"

  # Ensure Istio is deployed before the beacon
  # depends_on = [module.istio]
}

# Outputs to verify deployment
output "istio_beacon_app_name" {
  value       = module.istio_beacon.app_name
  description = "The name of the deployed Istio Beacon application"
}

output "istio_beacon_endpoints" {
  value       = module.istio_beacon.endpoints
  description = "Available endpoints for the Istio Beacon charm"
}
