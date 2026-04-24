# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes resource metadata model."""

from typing import Dict, Optional

from pydantic import BaseModel


class Metadata(BaseModel):
    """Global metadata schema for Kubernetes resources."""

    name: str
    namespace: str
    labels: Optional[Dict[str, str]] = None
    annotations: Optional[Dict[str, str]] = None
