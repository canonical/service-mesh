# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Lightkube type aliases."""

from typing import List, Optional, Set, Type, Union

from lightkube.core.resource import GlobalResource, NamespacedResource

LightkubeResourceType = Union[NamespacedResource, GlobalResource]
LightkubeResourcesList = List[LightkubeResourceType]
LightkubeResourceTypesSet = Optional[Set[Type[LightkubeResourceType]]]
