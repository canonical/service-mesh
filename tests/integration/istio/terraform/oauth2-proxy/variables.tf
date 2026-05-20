variable "model" {
  description = "The Juju model to deploy oauth2-proxy to"
  type        = string
}

variable "app_name" {
  description = "The Juju application name"
  type        = string
  default     = "oauth2"
}

variable "channel" {
  description = "Channel to deploy the oauth2-proxy charm from"
  type        = string
  default     = "latest/edge"
}

variable "config" {
  description = "Configuration for the oauth2-proxy charm"
  type        = map(string)
  default     = {}
}
