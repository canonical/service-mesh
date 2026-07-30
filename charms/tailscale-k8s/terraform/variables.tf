variable "app_name" {
  description = "Name to give the deployed application"
  type        = string
  default     = "tailscale"
}

variable "channel" {
  description = "Channel that the charm is deployed from"
  type        = string
  default     = "latest/edge"

  validation {
    condition     = can(regex("^(latest|dev)/(stable|candidate|beta|edge)$", var.channel))
    error_message = "The channel must be '<track>/<risk>' where track is 'latest' or 'dev' and risk is one of stable, candidate, beta, edge. e.g. 'latest/edge'."
  }
}

variable "config" {
  description = "Map of the charm configuration options"
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "String listing constraints for this application"
  type        = string
  # FIXME: Passing an empty constraints value to the Juju Terraform provider currently
  # causes the operation to fail due to https://github.com/juju/terraform-provider-juju/issues/344
  default = "arch=amd64"
}

variable "model_uuid" {
  description = "Reference to an existing model resource or data source for the model to deploy to"
  type        = string
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
}

variable "storage_directives" {
  description = "Map of storage used by the application, which defaults to 1 GB, allocated by Juju"
  type        = map(string)
  default     = {}
}

variable "units" {
  description = "Unit count/scale"
  type        = number
  default     = 1
}
