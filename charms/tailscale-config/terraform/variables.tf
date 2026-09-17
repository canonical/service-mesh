variable "app_name" {
  description = "Name to give the deployed application"
  type        = string
  default     = "tailscale-config"
}

variable "channel" {
  description = "Channel that the charm is deployed from"
  type        = string
  default     = "dev/edge"

  validation {
    condition     = can(regex("^(latest|dev)/(stable|candidate|beta|edge)$", var.channel))
    error_message = "The channel must be '<track>/<risk>' where track is 'latest' or 'dev' and risk is one of stable, candidate, beta, edge. e.g. 'latest/edge'."
  }
}

variable "config" {
  # Secret values MUST NOT be passed as Terraform variables. Python sets the
  # root-credential secret URI externally, outside Terraform. Provider reads
  # may persist that URI in Terraform state, but not the secret contents.
  description = "Map of the charm configuration options"
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "String listing constraints for this application"
  type        = string
  default     = "arch=amd64"
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

variable "units" {
  description = "Unit count/scale"
  type        = number
  default     = 1
}
