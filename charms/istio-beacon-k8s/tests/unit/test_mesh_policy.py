# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from charmlibs.interfaces.service_mesh import (
    Endpoint,
    MeshPolicy,
    PolicyTargetType,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "policy_data,should_raise,error_message",
    [
        # Valid app policy with target_app_name
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_app_name": "target-app",
                "target_type": PolicyTargetType.app,
                "endpoints": [Endpoint(ports=[80])],
            },
            False,
            None,
        ),
        # Valid app policy with target_service
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_service": "my-service",
                "target_type": PolicyTargetType.app,
                "endpoints": [Endpoint(ports=[80])],
            },
            False,
            None,
        ),
        # Invalid app policy - neither target_app_name nor target_service
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_type": PolicyTargetType.app,
                "endpoints": [Endpoint(ports=[80])],
            },
            True,
            f"Bad policy configuration. Neither target_app_name nor target_service specified for MeshPolicy with target_type {PolicyTargetType.app}",
        ),
        # Invalid app policy - has target_selector_labels
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_app_name": "target-app",
                "target_selector_labels": {"app": "my-app"},
                "target_type": PolicyTargetType.app,
                "endpoints": [Endpoint(ports=[80])],
            },
            True,
            f"Bad policy configuration. MeshPolicy with target_type {PolicyTargetType.app} does not support target_selector_labels.",
        ),
        # Valid unit policy with target_app_name
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_app_name": "target-app",
                "target_type": PolicyTargetType.unit,
                "endpoints": [Endpoint(ports=[8080])],
            },
            False,
            None,
        ),
        # Valid unit policy with target_selector_labels
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_selector_labels": {"app": "my-app"},
                "target_type": PolicyTargetType.unit,
                "endpoints": [Endpoint(ports=[8080])],
            },
            False,
            None,
        ),
        # Invalid unit policy - both target_app_name and target_selector_labels
        (
            {
                "source_app_name": "source-app",
                "source_namespace": "source-ns",
                "target_namespace": "target-ns",
                "target_app_name": "target-app",
                "target_selector_labels": {"app": "my-app"},
                "target_type": PolicyTargetType.unit,
                "endpoints": [Endpoint(ports=[8080])],
            },
            True,
            f"Bad policy configuration. MeshPolicy with target_type {PolicyTargetType.unit} cannot specify both target_app_name and target_selector_labels.",
        ),
    ],
)
def test_mesh_policy_validation(policy_data, should_raise, error_message):
    """Test MeshPolicy pydantic validations for various configurations."""
    if should_raise:
        with pytest.raises(ValidationError) as exc_info:
            MeshPolicy(**policy_data)
        assert error_message in str(exc_info.value)
    else:
        policy = MeshPolicy(**policy_data)
        assert policy.source_app_name == "source-app"
