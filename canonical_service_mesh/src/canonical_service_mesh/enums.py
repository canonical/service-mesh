# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared enumerations for Charmed Service Mesh."""

from enum import Enum


class Method(str, Enum):
    """HTTP method."""

    connect = "CONNECT"
    delete = "DELETE"
    get = "GET"
    head = "HEAD"
    options = "OPTIONS"
    patch = "PATCH"
    post = "POST"
    put = "PUT"
    trace = "TRACE"


class Action(str, Enum):
    """Action to take when an authorization policy rule matches."""

    allow = "ALLOW"
    deny = "DENY"
    custom = "CUSTOM"


class MeshType(str, Enum):
    """Supported service mesh types."""

    istio = "istio"


class PolicyTargetType(str, Enum):
    """Target type for policy classes."""

    app = "app"
    unit = "unit"
