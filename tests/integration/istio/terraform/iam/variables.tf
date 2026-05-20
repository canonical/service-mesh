variable "model" {
  description = "Name of the Juju model for IAM deployment"
  type        = string
}

variable "certificates_channel" {
  description = "Channel for self-signed-certificates"
  type        = string
  default     = "1/stable"
}

variable "traefik_channel" {
  description = "Channel for traefik-k8s"
  type        = string
  default     = "latest/stable"
}

variable "postgresql_channel" {
  description = "Channel for postgresql-k8s"
  type        = string
  default     = "14/stable"
}
