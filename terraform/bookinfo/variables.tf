variable "model" {
  description = "The Juju model to deploy to"
  type        = string
}

variable "channel" {
  description = "Channel to deploy the charms from"
  type        = string
  default     = "latest/stable"
}

variable "beacon_app_name" {
  type        = string
  default     = null
  description = "Name of the istio-beacon application. If provided, enables service mesh integration."
}

variable "beacon_service_mesh_endpoint" {
  type        = string
  default     = null
  description = "Endpoint name for the beacon's service mesh integration (e.g., 'service-mesh')."
}
