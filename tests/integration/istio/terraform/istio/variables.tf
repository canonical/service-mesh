variable "model" {
  description = "The Juju model to deploy istio to"
  type        = string
}

variable "channel" {
  description = "Channel to deploy istio from"
  type        = string
  default     = "dev/edge"
}

variable "config" {
  description = "Configuration for the istio-k8s charm"
  type        = map(string)
  default     = {}
}
