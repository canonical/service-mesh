"""Integration tests for authenticated ingress with the Canonical Identity Platform."""

from pytest_bdd import scenarios

# Load all scenarios from the iam feature file
scenarios("../features/iam.feature")
