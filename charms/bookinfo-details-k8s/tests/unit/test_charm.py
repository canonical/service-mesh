"""Unit tests for details charm."""

import unittest

import ops.testing

from charm import DetailsK8sCharm


class TestDetailsCharm(unittest.TestCase):
    """Test cases for DetailsK8sCharm."""

    def setUp(self):
        """Set up test fixtures."""
        self.harness = ops.testing.Harness(DetailsK8sCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_charm_initializes(self):
        """Test that charm initializes without errors."""
        self.assertIsInstance(self.harness.charm, DetailsK8sCharm)

    def test_pebble_ready_sets_status(self):
        """Test that pebble ready event sets appropriate status."""
        self.harness.container_pebble_ready("bookinfo-details")
        self.assertIsInstance(
            self.harness.model.unit.status,
            (ops.WaitingStatus, ops.ActiveStatus, ops.MaintenanceStatus),
        )
