/**
 * # Bookinfo Details K8s Terraform Module
 *
 * This is a Terraform module facilitating the deployment of bookinfo-details-k8s, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs).
 *
 * ## Usage
 *
 * Create `main.tf`:
 *
 * ```hcl
 * module "details" {
 *   source  = "git::https://github.com/canonical/service-mesh//charms/bookinfo-details-k8s/terraform"
 *   model   = juju_model.k8s.name
 *   channel = "edge"
 * }
 * ```
 *
 * ```sh
 * $ terraform apply
 * ```
 */

resource "juju_application" "details" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "bookinfo-details-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
