# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""CRD-presence steps for the envoy-ai-controller-k8s suite."""

from pytest_bdd import then

from tests.integration.helpers import AI_GATEWAY_CRDS, crd_exists


@then("the following CRDs exist on the cluster:")
def crds_exist(datatable: list) -> None:
    """Assert each CRD named in the table (skipping the header row) exists."""
    for row in datatable[1:]:
        name = row[0].strip()
        assert crd_exists(name), f"expected CRD {name} to exist"


@then("the AI Gateway CRDs exist on the cluster")
def ai_gateway_crds_exist() -> None:
    """Assert the full AI Gateway CRD set the controller installs is present."""
    for name in AI_GATEWAY_CRDS:
        assert crd_exists(name), f"expected CRD {name} to exist"
