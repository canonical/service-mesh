variable "model" {
  description = "The Juju model to deploy istio-ingress to"
  type        = string
}

variable "channel" {
  description = "Channel to deploy the istio-ingress charm from"
  type        = string
  default     = "2/edge"
}

variable "config" {
  description = "Configuration for the istio-ingress charm"
  type        = map(string)
  default     = {}
}
