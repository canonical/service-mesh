# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Placeholder so the integration suite is collectable.

The BDD scenarios under ``tests/integration/features/`` are not yet
fully implemented. This is just a placeholder for the CI. Remove it
when the integration tests are fully implemented.
"""

import pytest


@pytest.mark.skip(reason="Integration tests not yet fully implemented")
def test_placeholder():
    pass
