"""Integration tests for Istio authorization policies."""

from pytest_bdd import scenarios

# Load all scenarios from the authorization policies feature file
scenarios("../features/authorization-policies.feature")
