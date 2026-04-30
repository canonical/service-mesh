output "oauth_offer_url" {
  description = "The Hydra OAuth Juju offer URL"
  value       = module.hydra.oauth_offer_url
}

output "send_ca_cert_offer_url" {
  description = "The send-ca-cert Juju offer URL"
  value       = juju_offer.send_ca_certificate.url
}

output "certificates_offer_url" {
  description = "The certificates Juju offer URL"
  value       = juju_offer.certificates.url
}
