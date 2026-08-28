"""Unit tests for productpage charm."""

import unittest

import ops.testing

from charm import ProductPageK8sCharm


class TestProductPageCharm(unittest.TestCase):
    """Test cases for ProductPageK8sCharm."""

    def setUp(self):
        """Set up test fixtures."""
        self.harness = ops.testing.Harness(ProductPageK8sCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_charm_initializes(self):
        """Test that charm initializes without errors."""
        self.assertIsInstance(self.harness.charm, ProductPageK8sCharm)

    def test_pebble_ready_sets_status(self):
        """Test that pebble ready event sets appropriate status."""
        self.harness.container_pebble_ready("bookinfo-productpage")
        self.assertIsInstance(
            self.harness.model.unit.status,
            (ops.WaitingStatus, ops.ActiveStatus, ops.MaintenanceStatus),
        )
