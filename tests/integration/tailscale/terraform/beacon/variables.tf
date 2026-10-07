variable "model_uuid" {
  description = "UUID of the Juju model to deploy the Tailscale beacon to"
  type        = string
}

variable "app_name" {
  description = "Name to give the deployed application"
  type        = string
  default     = "tailscale-beacon-k8s"
}

variable "channel" {
  description = "Channel to deploy the charm from"
  type        = string
  default     = "dev/edge"
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
}

variable "config" {
  description = "Non-secret charm configuration"
  type        = map(string)
  default     = {}
}
