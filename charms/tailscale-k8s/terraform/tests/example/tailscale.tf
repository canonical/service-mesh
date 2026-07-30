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
resource "juju_model" "tailscale_test" {
  name = "tailscale-test"

  # Specify your cloud/substrate
  # For example, for microk8s:
  # cloud {
  #   name = "microk8s"
  # }

  # For other Kubernetes clouds, adjust accordingly
}

# Deploy Tailscale using the module
module "tailscale" {
  source = "../.."

  # Required: reference to the model
  model_uuid = juju_model.tailscale_test.uuid

  # Required: specify the channel
  channel = "latest/edge"

  # Optional: customize the deployment
  app_name = "tailscale"
  units    = 1

  # Optional: charm configuration
  config = {
    # URL of the Tailscale control plane. Leave empty for Tailscale SaaS.
    # login-server = "https://headscale.example.com"

    # Tags applied to the operator device and proxy pods.
    operator-tags = "tag:k8s-operator"
    proxy-tags    = "tag:k8s"
  }

  # Optional: constraints
  constraints = "arch=amd64"
}

# Outputs to verify deployment
output "tailscale_app_name" {
  value       = module.tailscale.app_name
  description = "The name of the deployed application"
}
