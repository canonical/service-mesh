variable "model_uuid" {
  description = "UUID of the Juju model to deploy Bookinfo to"
  type        = string
}

variable "channel" {
  description = "Channel to deploy the Bookinfo charms from"
  type        = string
  default     = "latest/stable"
}

variable "productpages" {
  description = "Productpage applications keyed by application name, sharing one details application"
  type = map(object({
    units  = optional(number, 1)
    config = optional(map(string), {})
  }))
  default = { productpage = {} }
}
