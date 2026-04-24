# canonical_service_mesh

A shared utility library for the Charmed Service Mesh ecosystem.

## Purpose

The Charmed Service Mesh ecosystem will contain charms that integrate service mesh technologies into the Juju ecosystem. These charms and their interface libraries share a significant amount of common code: Pydantic models for Kubernetes resource creation and service mesh CRD resources, lightkube-based resource management, label generation and authorization policies etc.

This package is the single home for all of that shared utility code. By centralizing it here, every charm and interface library depends on one well-maintained package instead of copying code between repositories or pulling from multiple helper packages.

## Ecosystem

The ecosystem has three layers:

1. **This package (`canonical_service_mesh`)** provides models, resource managers, and helpers. It has no knowledge of Juju relations or charm lifecycle, which keeps it testable and reusable.
2. **Interface libraries** (via the `charmlibs` monorepo) define the relation databag schemas and the interface classes. They import from this package.
3. **Charms** contain purely the charm specific logic and consume the interface and the canonical_service_mesh libraries.

## Package structure

### `enums`

Shared enumerations used across the ecosystem.

### `models`

Pydantic models for Kubernetes and service mesh resources. The top-level `models` module contains generic Kubernetes Gateway API resource models. The `models.istio` subpackage contains Istio-specific CRD specs for authorization policies and request authentication.

### `utils`

Helper functions for Kubernetes label generation, Juju identity resolution, and service mesh specific operations like label ConfigMap reconciliation and policy resource construction.

### `k8s`

Kubernetes resource management built on lightkube. The `k8s.resource_manager` subpackage provides declarative resource lifecycle management with label-based ownership, policy resource management, and batch operations. The `k8s.types` subpackage defines lightkube type aliases and custom resource definitions.
