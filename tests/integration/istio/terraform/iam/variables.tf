variable "core_model" {
  description = "Name of the Juju model for core dependencies"
  type        = string
  default     = "core"
}

variable "iam_model" {
  description = "Name of the Juju model for the Identity Platform"
  type        = string
  default     = "iam"
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
