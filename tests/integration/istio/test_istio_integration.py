"""Integration tests for Istio service mesh."""

from pytest_bdd import scenarios

# Load all scenarios from the feature file
scenarios("features/istio-integration.feature")
