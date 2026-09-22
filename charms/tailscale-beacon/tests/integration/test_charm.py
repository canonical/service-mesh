# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Placeholder integration tests for the tailscale-beacon charm.

The shared `canonical/observability` charm quality-checks workflow falls back to
the repository-root `tests/integration` directory (the Istio suites) when a charm
ships no integration tests of its own. This module keeps the charm's own
integration suite non-empty so that fallback never kicks in.

Replace this with real tests once the charm has integration coverage.
"""


def test_placeholder():
    """Keep the integration suite collectable until real tests are added."""
