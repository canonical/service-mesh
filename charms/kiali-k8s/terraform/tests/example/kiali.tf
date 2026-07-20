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
resource "juju_model" "kiali_test" {
  name = "kiali-test"

  # Specify your cloud/substrate
  # For example, for microk8s:
  # cloud {
  #   name = "microk8s"
  # }

  # For other Kubernetes clouds, adjust accordingly
}

# Deploy Istio using the istio-k8s-operator module
module "istio" {
  source   = "git::https://github.com/canonical/istio-k8s-operator//terraform"
  model    = juju_model.kiali_test.name
  channel  = "2/edge"
  app_name = "istio"
  units    = 1
}

# Deploy Prometheus using the prometheus-k8s-operator module
module "prometheus" {
  source     = "git::https://github.com/canonical/prometheus-k8s-operator//terraform"
  model_uuid = juju_model.kiali_test.uuid
  channel    = "2/edge"
  app_name   = "prometheus"
  units      = 1
}

# Deploy Istio Ingress using the module (depends on Istio being deployed first)
module "kiali" {
  source = "../.."

  # Required: reference to the model
  model_uuid = juju_model.kiali_test.uuid

  # Required: specify the channel
  channel = "2/edge"

  # Optional: customize the deployment
  app_name = "kiali"
  units    = 1

  # Optional: charm configuration
  config = {
    # Toggle whether Kiali is view-only
    view-only-mode = true
  }

  # Optional: constraints
  constraints = "arch=amd64"

  # Ensure Istio is deployed before the ingress
  depends_on = [module.istio]
}

resource "juju_integration" "kiali_prometheus" {
  model = juju_model.kiali_test.name

  application {
    name     = module.kiali.app_name
    endpoint = module.kiali.endpoints.prometheus-api
  }

  application {
    name     = module.prometheus.app_name
    endpoint = module.prometheus.endpoints.prometheus_api
  }
}

resource "juju_integration" "kiali_istio_metadata" {
  model = juju_model.kiali_test.name

  application {
    name     = module.kiali.app_name
    endpoint = module.kiali.endpoints.istio-metadata
  }

  application {
    name     = module.istio.app_name
    endpoint = module.istio.endpoints.istio_metadata
  }
}

# Outputs to verify deployment
output "kiali_app_name" {
  value       = module.kiali.app_name
  description = "The name of the deployed application"
}

output "kiali_endpoints" {
  value       = module.kiali.endpoints
  description = "Available endpoints for the application"
}

