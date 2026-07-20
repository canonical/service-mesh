# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""CRD-presence steps for the envoy-controller-k8s suite."""

from pytest_bdd import then

from tests.integration.helpers import GATEWAY_API_CRDS, crd_exists


@then("the following CRDs exist on the cluster:")
def crds_exist(datatable: list) -> None:
    """Assert each CRD named in the table (skipping the header row) exists."""
    for row in datatable[1:]:
        name = row[0].strip()
        assert crd_exists(name), f"expected CRD {name} to exist"


@then("the following CRDs do not exist on the cluster:")
def crds_do_not_exist(datatable: list) -> None:
    """Assert each CRD named in the table (skipping the header row) is absent."""
    for row in datatable[1:]:
        name = row[0].strip()
        assert not crd_exists(name), f"expected CRD {name} to be absent"


@then("the Gateway API CRDs exist on the cluster")
def gateway_api_crds_exist() -> None:
    """Assert the full Gateway API CRD set the controller installs is present."""
    for name in GATEWAY_API_CRDS:
        assert crd_exists(name), f"expected CRD {name} to exist"
