from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from ops.testing import Harness

from charm import IstioIngressCharm

# Example inputs for the test cases
test_inputs = [
    # Valid Hostnames
    ("example.com", True),
    ("subdomain.example.com", True),
    ("my-app.service.local", True),
    ("a1b2c3.example.co.uk", True),
    ("xn--d1acufc.xn--p1ai", True),  # Punycode for internationalized domain name
    ("a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z", True),  # Maximum label count
    ("localhost", True),
    # Edge Cases (should match)
    ("a.b", True),  # Very short hostname with two labels
    ("a--b.example.com", True),  # Double hyphen inside label
    ("1234567890.com", True),  # All numeric but with a valid TLD
    ("xn--80ak6aa92e.com", True),  # Punycode for internationalized domain
    ("1.2.3.example.com", True),  # Mix of numeric and alphabetical labels
    # Invalid Hostnames
    ("-example.com", False),  # Starts with a hyphen
    ("*-valid.example.org", False),
    ("example-.com", False),  # Ends with a hyphen
    ("*.example.com", False),  # Wildcard at the start
    ("example..com", False),  # Double dot
    (".example.com", False),  # Starts with a dot
    ("example.com.", False),  # Ends with a dot
    ("exa$mple.com", False),  # Contains invalid characters
    ("example.com..", False),  # Ends with a double dot
    # IP Addresses (Should Not Match)
    ("192.168.1.192", False),
    ("10.0.0.1", False),
    ("255.255.255.255", False),
    # Edge Cases (Should Not Match)
    ("a.*.com", False),  # Wildcard in the middle, which is not valid
    ("a.b-", False),  # Label ends with a hyphen
]


@pytest.fixture()
def harness():
    harness = Harness(IstioIngressCharm)
    harness.set_model_name("istio-system")
    yield harness
    harness.cleanup()


@pytest.mark.parametrize("hostname, expected", test_inputs)
def test_is_valid_hostname(hostname: str, expected: bool, harness: Harness[IstioIngressCharm]):
    """Test the _is_valid_hostname method with various hostname inputs."""
    harness.begin()
    charm = harness.charm
    result = charm._is_valid_hostname(hostname)
    assert result == expected, f"Hostname {hostname}: expected {expected}, got {result}"


def test_is_valid_gateway(harness: Harness[IstioIngressCharm]):
    harness.begin()
    charm = harness.charm

    with patch.object(charm, "_get_gateway_resource_manager") as mock_krm, patch.object(
        charm, "_construct_gateway"
    ) as mock_construct_gateway, patch.object(charm, "_is_ready") as mock_is_ready:

        mock_krm.return_value.reconcile = MagicMock()
        mock_construct_gateway.return_value = MagicMock()
        mock_is_ready.return_value = True
        harness.set_leader(True)
        harness.update_config({"external_hostname": "foo.bar"})

        # Ensure resource manager and waypoint construction were called
        mock_krm.return_value.reconcile.assert_called()
        mock_construct_gateway.assert_called()


@pytest.mark.parametrize(
    "external_hostname, expected_result",
    [
        ("foo.bar", "foo.bar"),
        ("invalid_hostname!", None),
        ("another.valid.hostname", "another.valid.hostname"),
        ("", "10.1.1.1"),  # Edge case: empty hostname
    ],
)
def test_external_hostname_config(
    harness: Harness[IstioIngressCharm], external_hostname, expected_result
):
    harness.begin()
    charm = harness.charm

    with patch.object(charm, "_get_gateway_resource_manager") as mock_krm, patch.object(
        charm, "_construct_gateway"
    ) as mock_construct_gateway, patch.object(charm, "_is_ready") as mock_is_ready, patch(
        "charm.IstioIngressCharm._get_lb_external_address", new_callable=PropertyMock
    ) as mock_get_lb_external_address:

        mock_krm.return_value.reconcile = MagicMock()
        mock_construct_gateway.return_value = MagicMock()
        mock_is_ready.return_value = True
        harness.set_leader(True)
        mock_get_lb_external_address.return_value = "10.1.1.1"
        # Unset the charm's cache of the external hostname.  This is required because while real config-changed event would
        # create a new instance of the charm (and thus have a clean cache), the test harness reuses the same instance and
        # the cache is populated on harness.begin().
        charm._ingress_url_ = None
        harness.update_config({"external_hostname": external_hostname})
        harness.evaluate_status()
        if expected_result:
            assert charm.unit.status.message == f"Serving at {expected_result}"
        else:
            assert (
                charm.unit.status.message
                == "Invalid hostname provided, Please ensure this adheres to RFC 1123."
            )
        assert charm._ingress_url == expected_result


def test_external_hostname_config_cached(harness: Harness[IstioIngressCharm]):
    """Test that the external_hostname config is cached after the first access."""
    expected_external_host = "example.com"
    harness.update_config({"external_hostname": expected_external_host})
    harness.begin()
    charm = harness.charm

    # Fetch the external_host, which should be the config value
    actual_external_host = charm._ingress_url
    assert actual_external_host == expected_external_host

    # Change the config and then access it again to confirm we get the cached value
    # We need mocks here because `harness.update_config()` fires a config-changed event
    with patch.object(charm, "_get_gateway_resource_manager"), patch.object(
        charm, "_construct_gateway"
    ), patch.object(charm, "_is_ready"), patch(
        "charm.IstioIngressCharm._get_lb_external_address", new_callable=PropertyMock
    ):
        harness.set_leader(True)
        harness.update_config({"external_hostname": "new.com"})
        assert charm._ingress_url == expected_external_host
