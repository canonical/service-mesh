variable "model" {
  description = "The Juju model to deploy istio to"
  type        = string
}

variable "channel" {
  description = "Channel to deploy istio from"
  type        = string
  default     = "2/edge"
}
