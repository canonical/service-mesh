"""Integration tests for Istio beacon managed mode."""

from pytest_bdd import scenarios

# Load all scenarios from the managed-mode feature file
scenarios("features/managed-mode.feature")
