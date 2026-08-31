#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared integration-test fixtures."""

import json
import subprocess

import pytest


def _kubectl(*args, namespace=None):
    """Run a kubectl command, returning the CompletedProcess."""
    cmd = ["kubectl"]
    if namespace:
        cmd += ["-n", namespace]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture(scope="module", autouse=True)
def strip_stuck_tailscale_finalizers(ops_test):
    """Safety net so a leftover `tailscale.com/finalizer` can't wedge teardown.

    The upstream Tailscale operator puts a `tailscale.com/finalizer` on every
    `loadBalancerClass: tailscale` Service. If the operator is removed before
    those Services are deleted (e.g. model teardown, or `destroy-model --force`),
    the finalizer is never cleared, so the Service — and hence the namespace, and
    hence the model — is stuck deleting forever.

    Tests that create such Services should delete them while the operator is
    still running (see test_headscale.cleanup_tailscale_lb_services). This
    module-scoped fixture is a last-resort catch-all: after every integration
    module it strips any remaining `tailscale.com/finalizer` from Services in the
    model namespace so `destroy-model` never hangs.
    """
    yield
    namespace = ops_test.model.name
    result = _kubectl("get", "svc", "-o", "json", namespace=namespace)
    if result.returncode != 0:
        return
    try:
        services = json.loads(result.stdout).get("items", [])
    except json.JSONDecodeError:
        return
    for svc in services:
        finalizers = svc.get("metadata", {}).get("finalizers") or []
        if any("tailscale.com" in f for f in finalizers):
            name = svc["metadata"]["name"]
            _kubectl(
                "patch", "svc", name, "--type=json",
                "-p", '[{"op":"remove","path":"/metadata/finalizers"}]',
                namespace=namespace,
            )
