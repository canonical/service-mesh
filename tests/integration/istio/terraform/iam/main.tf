# Reference the pre-existing model (created by jubilant)
data "juju_model" "iam" {
  name  = var.model
  owner = "admin"
}

# --- Core applications ---

module "certificates" {
  source = "github.com/canonical/self-signed-certificates-operator//terraform?ref=rev443"

  model_uuid = data.juju_model.iam.uuid
  app_name   = "self-signed-certificates"

  channel = var.certificates_channel
  base    = "ubuntu@24.04"
}

module "traefik" {
  source = "github.com/canonical/traefik-k8s-operator//terraform?ref=rev259"

  model_uuid = data.juju_model.iam.uuid
  app_name   = "traefik-public"

  channel = var.traefik_channel

  depends_on = [module.certificates]
}

module "postgresql" {
  source = "github.com/shipperizer/postgresql-k8s-operator//terraform?ref=juju-tf%2F1.0"

  juju_model = data.juju_model.iam.uuid
  app_name   = "postgresql-k8s"

  channel = var.postgresql_channel
  base    = "ubuntu@22.04"

  storage_directives = {
    pgdata = "10G"
  }
}

# Core integration: traefik <-> certificates
resource "juju_integration" "traefik_certs" {
  application {
    name     = module.traefik.app_name
    endpoint = "certificates"
  }

  application {
    name     = module.certificates.app_name
    endpoint = "certificates"
  }

  model_uuid = data.juju_model.iam.uuid
}

# --- IAM applications ---

module "hydra" {
  source = "github.com/canonical/hydra-operator//terraform?ref=v2.0.0"

  model    = data.juju_model.iam.uuid
  app_name = "hydra"
  channel  = "latest/edge"
  base     = "ubuntu@22.04"

  depends_on = [module.postgresql]
}

module "kratos" {
  source = "github.com/canonical/kratos-operator//terraform?ref=v2.0.0"

  model    = data.juju_model.iam.uuid
  app_name = "kratos"
  channel  = "latest/edge"
  base     = "ubuntu@22.04"

  depends_on = [module.postgresql]
}

module "login_ui" {
  source = "github.com/canonical/identity-platform-login-ui-operator//terraform?ref=v2.1.0"

  model    = data.juju_model.iam.uuid
  app_name = "login-ui"
  channel  = "latest/edge"
  base     = "ubuntu@22.04"

  depends_on = [module.hydra, module.kratos]
}

# --- Direct integrations (replacing cross-model offers) ---

# Database integrations
resource "juju_integration" "hydra_database" {
  application {
    name     = module.hydra.app_name
    endpoint = "pg-database"
  }

  application {
    name     = module.postgresql.application_name
    endpoint = "database"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "kratos_database" {
  application {
    name     = module.kratos.app_name
    endpoint = "pg-database"
  }

  application {
    name     = module.postgresql.application_name
    endpoint = "database"
  }

  model_uuid = data.juju_model.iam.uuid
}

# Traefik route integrations
resource "juju_integration" "login_ui_public_route" {
  application {
    name     = module.traefik.app_name
    endpoint = "traefik-route"
  }

  application {
    name     = module.login_ui.app_name
    endpoint = "public-route"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "hydra_public_route" {
  application {
    name     = module.traefik.app_name
    endpoint = "traefik-route"
  }

  application {
    name     = module.hydra.app_name
    endpoint = "public-route"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "kratos_public_route" {
  application {
    name     = module.traefik.app_name
    endpoint = "traefik-route"
  }

  application {
    name     = module.kratos.app_name
    endpoint = "public-route"
  }

  model_uuid = data.juju_model.iam.uuid
}

# --- Internal IAM integrations ---

resource "juju_integration" "kratos_hydra_info" {
  application {
    name     = module.hydra.app_name
    endpoint = "hydra-endpoint-info"
  }

  application {
    name     = module.kratos.app_name
    endpoint = "hydra-endpoint-info"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "login_ui_hydra_info" {
  application {
    name     = module.hydra.app_name
    endpoint = "hydra-endpoint-info"
  }

  application {
    name     = module.login_ui.app_name
    endpoint = "hydra-endpoint-info"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "kratos_login_ui_info" {
  application {
    name     = module.kratos.app_name
    endpoint = "kratos-info"
  }

  application {
    name     = module.login_ui.app_name
    endpoint = "kratos-info"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "kratos_login_ui_ui_info" {
  application {
    name     = module.login_ui.app_name
    endpoint = "ui-endpoint-info"
  }

  application {
    name     = module.kratos.app_name
    endpoint = "ui-endpoint-info"
  }

  model_uuid = data.juju_model.iam.uuid
}

resource "juju_integration" "hydra_login_ui_ui_info" {
  application {
    name     = module.login_ui.app_name
    endpoint = "ui-endpoint-info"
  }

  application {
    name     = module.hydra.app_name
    endpoint = "ui-endpoint-info"
  }

  model_uuid = data.juju_model.iam.uuid
}

# --- Offers for external consumption ---

resource "juju_offer" "send_ca_certificate" {
  name             = "send-ca-cert"
  application_name = module.certificates.app_name
  endpoints        = ["send-ca-cert"]
  model_uuid       = data.juju_model.iam.uuid
}

resource "juju_offer" "certificates" {
  name             = "certificates"
  application_name = module.certificates.app_name
  endpoints        = ["certificates"]
  model_uuid       = data.juju_model.iam.uuid
}
