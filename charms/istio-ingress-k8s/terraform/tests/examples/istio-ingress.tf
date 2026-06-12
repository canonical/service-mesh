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
resource "juju_model" "istio_ingress_test" {
  name = "istio-ingress-test"

  # Specify your cloud/substrate
  # For example, for microk8s:
  # cloud {
  #   name = "microk8s"
  # }

  # For other Kubernetes clouds, adjust accordingly
}

# Deploy Istio using the istio-k8s-operator module
# module "istio" {
#   source     = "git::https://github.com/canonical/istio-k8s-operator//terraform"
#   model_uuid = juju_model.istio_ingress_test.uuid
#   channel    = "2/edge"
#   app_name   = "istio"
#   units      = 1
# }

# Deploy Istio Ingress using the module (depends on Istio being deployed first)
module "istio_ingress" {
  source = "../.."

  # Required: reference to the model
  model_uuid = juju_model.istio_ingress_test.uuid

  # Required: specify the channel
  channel = "2/edge"

  # Optional: customize the deployment
  app_name = "istio-ingress"
  units    = 1

  # Optional: charm configuration
  config = {
    # DNS name to be used by the ingress
    external_hostname = ""

    # Timeout for waypoint deployment readiness in seconds (default: 100)
    ready-timeout = 100
  }

  # Optional: constraints
  constraints = "arch=amd64"

  # Ensure Istio is deployed before the ingress
  # depends_on = [module.istio]
}

# Outputs to verify deployment
output "istio_ingress_app_name" {
  value       = module.istio_ingress.app_name
  description = "The name of the deployed Istio Ingress application"
}

output "istio_ingress_endpoints" {
  value       = module.istio_ingress.endpoints
  description = "Available endpoints for the Istio Ingress charm"
}

