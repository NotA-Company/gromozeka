"""Backend implementations for sandbox execution.

This package provides concrete implementations of the :class:`SandboxBackend`
protocol defined in :mod:`.base`. Each backend handles container lifecycle
operations (create, start, wait, kill, remove, inspect) and image management
independently, allowing the :class:`SandboxManager` to delegate work without
knowing which backend is active.

Modules:
    base: Defines the ``SandboxBackend`` protocol and dataclasses
        (``ContainerSpec``, ``ContainerOutcome``, ``ManagedContainerInfo``)
        used by all backends.
    docker: Docker-based implementation using the ``aiodocker`` async client.

Usage:
    Backends are instantiated with their respective configuration objects
    (e.g., ``DockerBackendConfig`` for ``DockerBackend``) and passed to
    :class:`SandboxManager`. The manager calls protocol methods like
    ``runOneshot()``, ``removeContainer()``, and ``healthcheck()`` without
    needing to know which backend is active.
"""

from .base import (
    SandboxBackend,
)
from .docker import DockerBackend

__all__ = [
    "SandboxBackend",
    "DockerBackend",
]
