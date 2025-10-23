module "istio_beacon" {
  source  = "git::https://github.com/canonical/istio-beacon-k8s-operator//terraform"
  model   = var.model
  channel = var.channel
  config  = var.config
}
