/**
 * # Istio Beacon K8s Terraform Module
 *
 * This is a Terraform module facilitating the deployment of istio-beacon-k8s, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs).
 *
 * For detailed information on Istio and Canonical Service Mesh, see the [official documentation](https://canonical-service-mesh-documentation.readthedocs-hosted.com/en/latest/).
 *
 * ## Usage
 *
 * Create `main.tf`:
 *
 * ```hcl
 * module "istio_beacon" {
 *   source  = "git::https://github.com/canonical/istio-beacon-k8s-operator//terraform"
 *   model   = juju_model.k8s.name
 *   channel = "1/stable"
 * }
 * ```
 *
 * ```sh
 * $ terraform apply
 * ```
 */

resource "juju_application" "istio_beacon" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "istio-beacon-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
