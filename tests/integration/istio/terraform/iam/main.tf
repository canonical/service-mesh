resource "juju_model" "core" {
  name = var.core_model
}

module "certificates" {
  source = "github.com/canonical/self-signed-certificates-operator//terraform?ref=rev443"

  model_uuid = juju_model.core.uuid
  app_name   = "self-signed-certificates"

  channel = var.certificates_channel
  base    = "ubuntu@24.04"

  depends_on = [juju_model.core]
}

module "traefik" {
  source = "github.com/canonical/traefik-k8s-operator//terraform?ref=rev259"

  model_uuid = juju_model.core.uuid
  app_name   = "traefik-public"

  channel = var.traefik_channel

  depends_on = [juju_model.core, module.certificates]
}

module "postgresql" {
  source = "github.com/shipperizer/postgresql-k8s-operator//terraform?ref=juju-tf%2F1.0"

  juju_model = juju_model.core.uuid
  app_name   = "postgresql-k8s"

  channel = var.postgresql_channel
  base    = "ubuntu@22.04"

  storage_directives = {
    pgdata = "10G"
  }

  depends_on = [juju_model.core]
}

resource "juju_offer" "traefik_route" {
  name             = "traefik-route"
  application_name = module.traefik.app_name
  endpoints        = ["traefik-route"]
  model_uuid       = juju_model.core.uuid
}

resource "juju_offer" "postgresql" {
  name             = "postgresql"
  application_name = module.postgresql.application_name
  endpoints        = ["database"]
  model_uuid       = juju_model.core.uuid
}

resource "juju_offer" "send_ca_certificate" {
  name             = "send-ca-cert"
  application_name = module.certificates.app_name
  endpoints        = ["send-ca-cert"]
  model_uuid       = juju_model.core.uuid
}

resource "juju_offer" "certificates" {
  name             = "certificates"
  application_name = module.certificates.app_name
  endpoints        = ["certificates"]
  model_uuid       = juju_model.core.uuid
}

resource "juju_integration" "traefik_certs" {
  application {
    name     = module.traefik.app_name
    endpoint = "certificates"
  }

  application {
    name     = module.certificates.app_name
    endpoint = "certificates"
  }

  model_uuid = juju_model.core.uuid
}

resource "juju_model" "iam" {
  name = var.iam_model
}

module "iam" {
  source = "git::https://github.com/canonical/iam-bundle-integration?ref=v1.0.2"
  model  = juju_model.iam.uuid

  postgresql_offer_url          = juju_offer.postgresql.url
  traefik_route_offer_url       = juju_offer.traefik_route.url
  send_ca_certificate_offer_url = juju_offer.send_ca_certificate.url

  depends_on = [juju_model.iam]
}
