output "productpage_app_names" {
  description = "Deployed productpage application names keyed by requested name"
  value       = { for name, app in module.productpage : name => app.app_name }
}

output "details_app_name" {
  description = "Name of the shared details application"
  value       = module.details.app_name
}
