# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import pathlib

import jubilant
import pytest

logger = logging.getLogger(__name__)

PRINCIPAL = "ubuntu"
PRINCIPAL_BASE = "ubuntu@24.04"
UNITS = 2
APP = "tailscale-beacon"
UNIT_0 = f"{APP}/0"
UNIT_1 = f"{APP}/1"

# Machine model operations (snap install, tailnet join) are slow.
DEPLOY_TIMEOUT = 30 * 60


def _tailscale_ip(juju: jubilant.Juju, unit: str) -> str:
    """Return the tailnet IPv4 address of a beacon unit."""
    result = juju.exec("/snap/bin/tailscale ip -4", unit=unit)
    ip = result.stdout.strip().splitlines()[0].strip()
    assert ip, f"No Tailscale IPv4 address reported by {unit}"
    return ip


@pytest.mark.juju_setup
def test_deploy_and_settle(charm: pathlib.Path, auth_key: str, juju: jubilant.Juju):
    """Deploy the beacon on two machines and wait for everything to go active.

    Deploys two ``ubuntu`` machines, attaches the tailscale-beacon subordinate to
    both, and supplies a manual auth-key credential (per the README manual flow).
    The beacon only reaches ``ActiveStatus`` once ``tailscale up`` succeeds
    against the live control plane, so ``all_active`` already proves the join.
    """
    juju.deploy(PRINCIPAL, app=PRINCIPAL, num_units=UNITS, base=PRINCIPAL_BASE)
    juju.deploy(charm, app=APP)

    # Supply the auth key as a granted user secret (README "Manual credentials").
    secret_uri = juju.add_secret("tailscale-auth", {"auth-key": auth_key})
    juju.grant_secret(secret_uri, APP)
    juju.config(APP, {"credentials": secret_uri})

    juju.integrate(f"{APP}:juju-info", f"{PRINCIPAL}:juju-info")

    juju.wait(jubilant.all_active, timeout=DEPLOY_TIMEOUT)


def test_beacons_have_tailnet_addresses(juju: jubilant.Juju):
    """Each beacon reports a distinct tailnet IPv4 address."""
    ip_0 = _tailscale_ip(juju, UNIT_0)
    ip_1 = _tailscale_ip(juju, UNIT_1)
    assert ip_0 != ip_1, f"Both beacons share the tailnet address {ip_0}"


def test_beacons_can_ping_each_other(juju: jubilant.Juju):
    """The two machines can reach each other over their tailnet addresses.

    ``juju.exec`` raises if ``ping`` exits non-zero, which fails the test.
    """
    ip_0 = _tailscale_ip(juju, UNIT_0)
    ip_1 = _tailscale_ip(juju, UNIT_1)

    juju.exec(f"ping -c 3 -w 10 {ip_1}", unit=UNIT_0)
    juju.exec(f"ping -c 3 -w 10 {ip_0}", unit=UNIT_1)
