# Centralized justfile for the service-mesh charms
set shell := ["bash", "-uc"]

charm_name := `echo ${PWD##*/} | sed 's/-operator$//'`  # Get the charm name from the folder name

export UV_FROZEN := "true"  # Prevent `uv run` from updating the lockfile
export PYTHONPATH := ".:./lib:./src"


[private]
@default:
    just --list

# Update the Terraform README with auto-generated content
[group("terraform")]
terraform-docs:
    which terraform-docs > /dev/null 2>&1 || { echo "× terraform-docs not found; you can install it via:"; echo "   snap install terraform-docs"; exit 1; }
    terraform-docs --config .tfdocs.yaml terraform
    @echo "✓ Terraform docs updated"

# Lint and validate the Terraform module
[group("terraform")]
terraform-lint:
    which terraform > /dev/null 2>&1 || { echo "× terraform not found"; exit 1; }
    cd terraform && terraform init -backend=false && terraform validate
    terraform fmt -recursive -check
    @echo "✓ Terraform lint passed"
