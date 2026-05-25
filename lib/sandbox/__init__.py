"""Sandboxed code execution library.

This library provides a safe, containerized environment for executing code with
configurable resource limits, security policies, and runtime management. It supports
multiple backend implementations (primarily Docker-based) and runtime environments
(Python, Node.js, etc.).

Main components:
- **SandboxManager**: High-level interface for managing sandbox instances, running code,
  and managing sessions/lifecycles.
- **SandboxBackend**: Abstract base class for backend implementations (e.g., Docker backend).
- **Runtime**: Abstraction for runtime environments (Python interpreters, Node.js runtimes, etc.).
- **MetadataStore**: Interface for persisting execution metadata, session state, and container info.

Core types:
- **SandboxConfig**: Top-level configuration object aggregating all sandbox settings.
- **DockerBackendConfig**: Docker-specific backend configuration (image, networking, volumes).
- **ConcurrencyConfig**: Controls parallel execution limits and resource contention.
- **SecurityConfig**: Security policies (network isolation, filesystem permissions, etc.).
- **StorageConfig**: Persistent storage paths and workspace management.
- **GcConfig**: Garbage collection policy for old containers/sessions.

Execution types:
- **RunResult**: Result of a code execution (stdout, stderr, exit code, resource usage).
- **RunInfo**: Metadata about an execution (runtime, timing, container reference).
- **ResourceLimits**: CPU, memory, and time constraints enforced during execution.
- **NetworkPolicy**: Network access controls (disabled, outbound-only, unrestricted).

Concurrency & Locking:
- **SessionLockRegistry**: Per-session semaphore-based run queue serialization.
- **GlobalRunLimiter**: Global concurrent run cap with timeout-based rejection.

Error hierarchy:
- **SandboxError**: Base class for all sandbox-related errors.
- **SessionError**: Errors related to session management (not found, busy, dropped).
- **RunError**: Errors during code execution (timeout, OOM, cancellation).
- **LibraryError**: Errors during library/package installation.
- **BackendError**: Backend-specific failures (Docker unavailable, image not found).

Usage example:
    ```python
    from lib.sandbox import SandboxManager, SandboxConfig

    config = SandboxConfig(backend=DockerBackendConfig(image="python:3.12"))
    manager = SandboxManager(config)
    result = manager.runCode("print('Hello, world!')")
    print(result.stdout)  # "Hello, world!\\n"
    ```
"""

from .backends.base import SandboxBackend
from .config import (
    BackendConfig,
    BasicRuntimeConfig,
    ConcurrencyConfig,
    DockerBackendConfig,
    GcConfig,
    InstallContainerConfig,
    SandboxConfig,
    SecurityConfig,
    SessionDefaults,
    StorageConfig,
)
from .enums import BackendName, RuntimeName
from .errors import (  # noqa: F401 — re-exported for convenience
    BackendError,
    ConfigError,
    DockerUnavailable,
    FileError,
    ImageBuildFailed,
    ImageNotFound,
    InvalidPackageSpec,
    LibraryError,
    LibraryInstallFailed,
    LibraryPoolLocked,
    MissingDependenciesError,
    PathOutsideWorkspace,
    RunCancelled,
    RunError,
    RunOomKilled,
    RunTimedOut,
    SandboxBusy,
    SandboxError,
    SandboxRuntimeError,
    SessionBusy,
    SessionDropped,
    SessionError,
    SessionNotFound,
    UnknownRuntime,
)
from .manager import SandboxManager
from .metadata.base import MetadataStore
from .runtimes.base import Runtime
from .types import (
    ContainerOutcome,
    ContainerSpec,
    FileContent,
    FileInfo,
    GcResult,
    HealthcheckResult,
    ManagedContainerInfo,
    NetworkPolicy,
    PackageInfo,
    ResourceLimits,
    RunInfo,
    RunResult,
    SessionInfo,
    ShutdownResult,
)

__all__ = [
    "BackendConfig",
    "BackendName",
    "ConcurrencyConfig",
    "ContainerOutcome",
    "ContainerSpec",
    "DockerBackendConfig",
    "GcConfig",
    "InstallContainerConfig",
    "ManagedContainerInfo",
    "MetadataStore",
    "BasicRuntimeConfig",
    "Runtime",
    "RuntimeName",
    "SandboxBackend",
    "SandboxConfig",
    "SandboxManager",
    "SandboxError",
    "SecurityConfig",
    "SessionDefaults",
    "SessionInfo",
    "StorageConfig",
    "ConfigError",
    "BackendError",
    "DockerUnavailable",
    "ImageNotFound",
    "ImageBuildFailed",
    "SessionError",
    "SessionNotFound",
    "SessionBusy",
    "SessionDropped",
    "SandboxRuntimeError",
    "UnknownRuntime",
    "MissingDependenciesError",
    "RunError",
    "RunTimedOut",
    "RunOomKilled",
    "RunCancelled",
    "LibraryError",
    "LibraryInstallFailed",
    "LibraryPoolLocked",
    "InvalidPackageSpec",
    "FileError",
    "PathOutsideWorkspace",
    "SandboxBusy",
    "FileContent",
    "FileInfo",
    "GcResult",
    "HealthcheckResult",
    "NetworkPolicy",
    "PackageInfo",
    "ResourceLimits",
    "RunInfo",
    "RunResult",
    "ShutdownResult",
]
