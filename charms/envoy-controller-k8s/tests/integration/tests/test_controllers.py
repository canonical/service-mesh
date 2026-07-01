# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Binds the controller workloads feature to its step definitions."""

from pytest_bdd import scenarios

scenarios("../features/controllers.feature")
