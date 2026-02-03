"""Integration tests for Istio hardened mode zero-trust enforcement."""

from pytest_bdd import scenarios

# Load all scenarios from the hardened-mode feature file
scenarios("../features/hardened-mode.feature")
