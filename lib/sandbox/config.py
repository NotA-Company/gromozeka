"""Configuration dataclasses for sandboxed code execution.

Defines all configuration dataclasses used to configure the sandbox library,
including storage paths, backend settings, session defaults, security
constraints, concurrency limits, garbage collection, and runtime-specific
options.  All classes use ``@dataclass(slots=True)`` with
``field(default_factory=...)`` for mutable defaults.

Classes:
    StorageConfig: Directory and file permission settings for sandbox storage.
    DockerBackendConfig: Docker-specific backend configuration.
    BackendConfig: Execution backend selection and backend-specific settings.
    SessionDefaults: Default session parameters (runtime, TTLs, timeouts).
    SecurityConfig: Container security constraints (user, capabilities, etc.).
    ConcurrencyConfig: Global and per-session concurrency limits.
    GcConfig: Garbage-collection schedule and retention policies.
    InstallContainerConfig: Resource limits for library-installation containers.
    PythonRuntimeConfig: Python-specific runtime configuration.
    SandboxConfig: Top-level configuration aggregating all sub-configs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal

from .enums import BackendName, RuntimeName
from .types import ResourceLimits


@dataclass(slots=True)
class StorageConfig:
    """Directory and file permission settings for sandbox storage.

    Attributes:
        rootDir: Host-side root directory for sandbox workspaces and data.
        dirMode: Octal permission mode for created directories.
        fileMode: Octal permission mode for created files.
    """

    rootDir: str
    dirMode: int = 0o700
    fileMode: int = 0o600

    @classmethod
    def fromDict(cls, data: dict) -> "StorageConfig":
        """Construct a StorageConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A StorageConfig instance.
        """
        if "root-dir" not in data:
            raise ValueError("Storage config requires root-dir value")
        return cls(
            rootDir=data["root-dir"],
            dirMode=int(data.get("dir-mode", "0700"), 0),
            fileMode=int(data.get("file-mode", "0600"), 0),
        )


@dataclass(slots=True)
class DockerBackendConfig:
    """Docker-specific backend configuration.

    Attributes:
        baseUrl: Docker daemon socket URL or TCP address.
        imagePullPolicy: When to pull container images — ``"never"``,
            ``"if-not-present"``, or ``"always"``.
    """

    baseUrl: str = "unix:///var/run/docker.sock"
    imagePullPolicy: Literal["never", "if-not-present", "always"] = "if-not-present"

    @classmethod
    def fromDict(cls, data: dict) -> "DockerBackendConfig":
        """Construct a DockerBackendConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A DockerBackendConfig instance.
        """
        return cls(
            baseUrl=data.get("base-url", "unix:///var/run/docker.sock"),
            imagePullPolicy=data.get("image-pull-policy", "if-not-present"),
        )


@dataclass(slots=True)
class BackendConfig:
    """Execution backend selection and backend-specific settings.

    Attributes:
        name: Which execution backend to use.
        docker: Configuration for the Docker backend (used when ``name`` is
            ``BackendName.DOCKER``).
    """

    name: BackendName = BackendName.DOCKER
    docker: DockerBackendConfig = field(default_factory=DockerBackendConfig)

    @classmethod
    def fromDict(cls, data: dict) -> "BackendConfig":
        """Construct a BackendConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A BackendConfig instance.
        """
        return cls(
            name=BackendName(data.get("name", "docker")),
            docker=DockerBackendConfig.fromDict(data.get("docker", {})),
        )


@dataclass(slots=True)
class SessionDefaults:
    """Default session parameters (runtime, TTLs, timeouts).

    Attributes:
        runtime: Default runtime for new sessions.
        idleTtlMinutes: Minutes of inactivity before a session is eligible
            for garbage collection.
        hardTtlMinutes: Absolute maximum session lifetime in minutes.
        runTimeoutSeconds: Default wall-clock timeout per code execution run.
    """

    runtime: RuntimeName = RuntimeName.PYTHON
    idleTtlMinutes: int = 30
    hardTtlMinutes: int = 120
    runTimeoutSeconds: int = 30

    @classmethod
    def fromDict(cls, data: dict) -> "SessionDefaults":
        """Construct a SessionDefaults from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A SessionDefaults instance.
        """
        return cls(
            runtime=RuntimeName(data.get("runtime", "python")),
            idleTtlMinutes=int(data.get("idle-ttl-minutes", 30)),
            hardTtlMinutes=int(data.get("hard-ttl-minutes", 120)),
            runTimeoutSeconds=int(data.get("run-timeout-seconds", 30)),
        )


@dataclass(slots=True)
class SecurityConfig:
    """Container security constraints (user, capabilities, etc.).

    Attributes:
        user: ``uid:gid`` string for the container process.
        readOnlyRootfs: If True, mount the container root filesystem as read-only.
        noNewPrivileges: If True, prevent privilege escalation inside the container.
        dropCapabilities: Linux capabilities to drop (typically ``("ALL",)``).
        privileged: If True, run the container in privileged mode (dangerous).
        envAllowlist: Tuple of environment variable names allowed through to
            the container.
    """

    user: str = "1000:1000"
    readOnlyRootfs: bool = True
    noNewPrivileges: bool = True
    dropCapabilities: tuple[str, ...] = ("ALL",)
    privileged: bool = False
    envAllowlist: tuple[str, ...] = ()

    @classmethod
    def fromDict(cls, data: dict) -> "SecurityConfig":
        """Construct a SecurityConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A SecurityConfig instance.
        """
        return cls(
            user=data.get("user", "1000:1000"),
            readOnlyRootfs=data.get("read-only-rootfs", True),
            noNewPrivileges=data.get("no-new-privileges", True),
            dropCapabilities=tuple(data.get("drop-capabilities", ("ALL",))),
            privileged=data.get("privileged", False),
            envAllowlist=tuple(data.get("env-allowlist", ())),
        )


@dataclass(slots=True)
class ConcurrencyConfig:
    """Global and per-session concurrency limits.

    Attributes:
        maxQueuedRunsPerSession: Maximum number of runs that can be queued for
            a single session before rejecting new requests.
        maxConcurrentRunsGlobal: Maximum number of runs executing concurrently
            across all sessions.
        globalQueueWaitSeconds: Maximum seconds a run waits in the global
            queue before timing out.
    """

    maxQueuedRunsPerSession: int = 4
    maxConcurrentRunsGlobal: int = 8
    globalQueueWaitSeconds: int = 60

    @classmethod
    def fromDict(cls, data: dict) -> "ConcurrencyConfig":
        """Construct a ConcurrencyConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A ConcurrencyConfig instance.
        """
        return cls(
            maxQueuedRunsPerSession=int(data.get("max-queued-runs-per-session", 4)),
            maxConcurrentRunsGlobal=int(data.get("max-concurrent-runs-global", 8)),
            globalQueueWaitSeconds=int(data.get("global-queue-wait-seconds", 60)),
        )


@dataclass(slots=True)
class GcConfig:
    """Garbage-collection schedule and retention policies.

    Attributes:
        enabled: If True, the GC loop runs at the configured interval.
        intervalSeconds: Seconds between GC sweeps.
        orphanContainerRetentionMinutes: Minutes to retain orphaned containers
            before removal.
        orphanWorkspaceRetentionMinutes: Minutes to retain orphaned workspace
            directories before removal.
        runRetentionMinutes: Minutes to retain completed run records before
            removal.
    """

    enabled: bool = True
    intervalSeconds: int = 60
    orphanContainerRetentionMinutes: int = 10
    orphanWorkspaceRetentionMinutes: int = 60
    runRetentionMinutes: int = 1440

    @classmethod
    def fromDict(cls, data: dict) -> "GcConfig":
        """Construct a GcConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A GcConfig instance.
        """
        return cls(
            enabled=data.get("enabled", True),
            intervalSeconds=int(data.get("interval-seconds", 60)),
            orphanContainerRetentionMinutes=int(data.get("orphan-container-retention-minutes", 10)),
            orphanWorkspaceRetentionMinutes=int(data.get("orphan-workspace-retention-minutes", 60)),
            runRetentionMinutes=int(data.get("run-retention-minutes", 1440)),
        )


@dataclass(slots=True)
class InstallContainerConfig:
    """Resource limits for library-installation containers.

    Attributes:
        timeoutSeconds: Wall-clock timeout for the install container.
        memoryMb: Memory limit in megabytes for the install container.
        pidsLimit: Maximum number of PIDs inside the install container.
    """

    timeoutSeconds: int = 600
    memoryMb: int = 1024
    pidsLimit: int = 256

    @classmethod
    def fromDict(cls, data: dict) -> "InstallContainerConfig":
        """Construct an InstallContainerConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            An InstallContainerConfig instance.
        """
        return cls(
            timeoutSeconds=int(data.get("timeout-seconds", 600)),
            memoryMb=int(data.get("memory-mb", 1024)),
            pidsLimit=int(data.get("pids-limit", 256)),
        )


@dataclass(slots=True)
class PythonRuntimeConfig:
    """Python-specific runtime configuration.

    Attributes:
        runImageTag: Docker image tag used for code execution.
        installImageTag: Docker image tag used for library installation.
        runDockerfile: Path to the Dockerfile for the run image.
        installDockerfile: Path to the Dockerfile for the install image.
        libMountPath: Container-side path where the library pool is mounted.
        env: Default environment variables injected into Python containers.
        installContainer: Resource limits for the install container.
    """

    runImageTag: str = "gromozeka-sandbox-python:run"
    installImageTag: str = "gromozeka-sandbox-python:install"
    runDockerfile: str = "lib/sandbox/runtimes/python/Dockerfile"
    installDockerfile: str = "lib/sandbox/runtimes/python/Dockerfile.install"
    libMountPath: str = "/sandbox/libs"
    env: dict[str, str] = field(
        default_factory=lambda: {
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "MPLBACKEND": "Agg",
            "PYTHONPATH": "/sandbox/libs",
        }
    )
    installContainer: InstallContainerConfig = field(default_factory=InstallContainerConfig)

    @classmethod
    def fromDict(cls, data: dict) -> "PythonRuntimeConfig":
        """Construct a PythonRuntimeConfig from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A PythonRuntimeConfig instance.
        """
        envRaw = data.get("env", {})
        env = {str(k): str(v) for k, v in envRaw.items()} if envRaw else {}
        return cls(
            runImageTag=data.get("run-image-tag", "gromozeka-sandbox-python:run"),
            installImageTag=data.get("install-image-tag", "gromozeka-sandbox-python:install"),
            runDockerfile=data.get("run-dockerfile", "lib/sandbox/runtimes/python/Dockerfile"),
            installDockerfile=data.get("install-dockerfile", "lib/sandbox/runtimes/python/Dockerfile.install"),
            libMountPath=data.get("lib-mount-path", "/sandbox/libs"),
            env=env,
            installContainer=InstallContainerConfig.fromDict(data.get("install-container", {})),
        )


@dataclass(slots=True)
class SandboxConfig:
    """Top-level configuration aggregating all sub-configs.

    Attributes:
        storage: Storage paths and permissions.
        backend: Execution backend selection and settings.
        defaults: Default session parameters.
        limits: Default resource limits for runs.
        security: Container security constraints.
        concurrency: Global and per-session concurrency limits.
        gc: Garbage-collection schedule and retention policies.
        runtimes: Mapping of :class:`RuntimeName` to runtime-specific config
            dataclasses (e.g. :class:`PythonRuntimeConfig`).  Default is an
            empty dict; callers populate it with the runtimes they need.
    """

    storage: StorageConfig
    backend: BackendConfig = field(default_factory=BackendConfig)
    defaults: SessionDefaults = field(default_factory=SessionDefaults)
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    gc: GcConfig = field(default_factory=GcConfig)
    runtimes: dict[RuntimeName, PythonRuntimeConfig | Any] = field(default_factory=dict)

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "SandboxConfig":
        """Construct a SandboxConfig from a dict.

        Args:
            data: Dictionary with top-level configuration keys.

        Returns:
            A SandboxConfig instance.
        """
        runtimesRaw = data.get("runtimes", {})
        runtimes: dict[RuntimeName, PythonRuntimeConfig | Any] = {}
        for name, rtData in runtimesRaw.items():
            rtName = RuntimeName(name)
            if not isinstance(rtData, dict):
                raise ValueError(f"Runtime config for {rtName} must be a dict, got {type(rtData).__name__}")
            if rtName == RuntimeName.PYTHON:
                runtimes[rtName] = PythonRuntimeConfig.fromDict(rtData)
            else:
                runtimes[rtName] = rtData
        return cls(
            storage=StorageConfig.fromDict(data.get("storage", {})),
            backend=BackendConfig.fromDict(data.get("backend", {})),
            defaults=SessionDefaults.fromDict(data.get("defaults", {})),
            limits=ResourceLimits.fromDict(data.get("limits", {})),
            security=SecurityConfig.fromDict(data.get("security", {})),
            concurrency=ConcurrencyConfig.fromDict(data.get("concurrency", {})),
            gc=GcConfig.fromDict(data.get("gc", {})),
            runtimes=runtimes,
        )
