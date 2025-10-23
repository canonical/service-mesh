variable "model" {
  description = "The Juju model to deploy istio-beacon to"
  type        = string
}

variable "channel" {
  description = "Channel to deploy the istio-beacon charm from"
  type        = string
  default     = "2/edge"
}

variable "config" {
  description = "Configuration for the istio-beacon charm"
  type        = map(string)
  default     = {}
}
