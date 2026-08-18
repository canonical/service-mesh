output "app_name" {
  value = juju_application.productpage.name
}

output "endpoints" {
  value = {
    # Provides
    website          = "website"
    provide_cmr_mesh = "provide-cmr-mesh"

    # Requires
    details          = "details"
    reviews          = "reviews"
    ratings          = "ratings"
    ingress          = "ingress"
    service_mesh     = "service-mesh"
    require_cmr_mesh = "require-cmr-mesh"
  }
}
