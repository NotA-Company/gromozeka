"""Tests for sandbox config dataclasses (lib.sandbox.config).

Covers:
- Default construction for each config dataclass (verify field defaults).
- Nested construction: build a full SandboxConfig with all nested configs.
- SandboxConfig.runtimes keyed by RuntimeName.
- PythonRuntimeConfig.env defaults include expected keys.
- slots=True verification for every config class.
- StorageConfig with explicit rootDir.
- DockerBackendConfig.imagePullPolicy accepts valid Literal values.
- Package-level re-export via ``from lib.sandbox import``.
"""

import pytest

from lib.sandbox import (
    BackendConfig,
    BackendName,
    ConcurrencyConfig,
    DockerBackendConfig,
    GcConfig,
    InstallContainerConfig,
    PythonRuntimeConfig,
    ResourceLimits,
    RuntimeName,
    SandboxConfig,
    SecurityConfig,
    SessionDefaults,
    StorageConfig,
)
from lib.sandbox.config import BackendConfig as BackendConfigDirect
from lib.sandbox.config import ConcurrencyConfig as ConcurrencyConfigDirect
from lib.sandbox.config import DockerBackendConfig as DockerBackendConfigDirect
from lib.sandbox.config import GcConfig as GcConfigDirect
from lib.sandbox.config import InstallContainerConfig as InstallContainerConfigDirect
from lib.sandbox.config import PythonRuntimeConfig as PythonRuntimeConfigDirect
from lib.sandbox.config import SandboxConfig as SandboxConfigDirect
from lib.sandbox.config import SecurityConfig as SecurityConfigDirect
from lib.sandbox.config import SessionDefaults as SessionDefaultsDirect
from lib.sandbox.config import StorageConfig as StorageConfigDirect

# ============================================================================
# All config classes for parametrized slots check
# ============================================================================

_ALL_CONFIG_CLASSES = (
    StorageConfig,
    DockerBackendConfig,
    BackendConfig,
    SessionDefaults,
    SecurityConfig,
    ConcurrencyConfig,
    GcConfig,
    InstallContainerConfig,
    PythonRuntimeConfig,
    SandboxConfig,
)


# ============================================================================
# slots=True verification
# ============================================================================


@pytest.mark.parametrize("cls", _ALL_CONFIG_CLASSES, ids=lambda c: c.__name__)
def testSlotsEnabled(cls: type) -> None:
    """Verify that every config dataclass uses slots=True.

    Args:
        cls: A config dataclass to check.

    Returns:
        None
    """
    assert hasattr(cls, "__slots__"), f"{cls.__name__} should have __slots__ (slots=True expected)"
    assert len(cls.__slots__) > 0, f"{cls.__name__} __slots__ should not be empty"


# ============================================================================
# StorageConfig
# ============================================================================


def testStorageConfigExplicitRootDir() -> None:
    """Verify StorageConfig construction with explicit rootDir.

    Returns:
        None
    """
    cfg = StorageConfig(rootDir="/tmp/test")
    assert cfg.rootDir == "/tmp/test"
    assert cfg.dirMode == 0o700
    assert cfg.fileMode == 0o600


def testStorageConfigExplicitAll() -> None:
    """Verify StorageConfig with all explicit values.

    Returns:
        None
    """
    cfg = StorageConfig(rootDir="/data/sandbox", dirMode=0o755, fileMode=0o644)
    assert cfg.rootDir == "/data/sandbox"
    assert cfg.dirMode == 0o755
    assert cfg.fileMode == 0o644


# ============================================================================
# DockerBackendConfig
# ============================================================================


def testDockerBackendConfigDefaults() -> None:
    """Verify DockerBackendConfig default values.

    Returns:
        None
    """
    cfg = DockerBackendConfig()
    assert cfg.baseUrl == "unix:///var/run/docker.sock"
    assert cfg.imagePullPolicy == "if-not-present"


def testDockerBackendConfigImagePullPolicyNever() -> None:
    """Verify DockerBackendConfig accepts imagePullPolicy='never'.

    Returns:
        None
    """
    cfg = DockerBackendConfig(imagePullPolicy="never")
    assert cfg.imagePullPolicy == "never"


def testDockerBackendConfigImagePullPolicyAlways() -> None:
    """Verify DockerBackendConfig accepts imagePullPolicy='always'.

    Returns:
        None
    """
    cfg = DockerBackendConfig(imagePullPolicy="always")
    assert cfg.imagePullPolicy == "always"


def testDockerBackendConfigImagePullPolicyIfNotPresent() -> None:
    """Verify DockerBackendConfig accepts imagePullPolicy='if-not-present'.

    Returns:
        None
    """
    cfg = DockerBackendConfig(imagePullPolicy="if-not-present")
    assert cfg.imagePullPolicy == "if-not-present"


def testDockerBackendConfigExplicitBaseUrl() -> None:
    """Verify DockerBackendConfig with explicit baseUrl.

    Returns:
        None
    """
    cfg = DockerBackendConfig(baseUrl="tcp://localhost:2375")
    assert cfg.baseUrl == "tcp://localhost:2375"


# ============================================================================
# BackendConfig
# ============================================================================


def testBackendConfigDefaults() -> None:
    """Verify BackendConfig default values.

    Returns:
        None
    """
    cfg = BackendConfig()
    assert cfg.name is BackendName.DOCKER
    assert isinstance(cfg.docker, DockerBackendConfig)
    assert cfg.docker.baseUrl == "unix:///var/run/docker.sock"


def testBackendConfigExplicitDocker() -> None:
    """Verify BackendConfig with an explicit DockerBackendConfig.

    Returns:
        None
    """
    dockerCfg = DockerBackendConfig(baseUrl="tcp://host:2375", imagePullPolicy="always")
    cfg = BackendConfig(name=BackendName.DOCKER, docker=dockerCfg)
    assert cfg.docker is dockerCfg
    assert cfg.docker.baseUrl == "tcp://host:2375"


# ============================================================================
# SessionDefaults
# ============================================================================


def testSessionDefaultsDefaults() -> None:
    """Verify SessionDefaults default values.

    Returns:
        None
    """
    defaults = SessionDefaults()
    assert defaults.runtime is RuntimeName.PYTHON
    assert defaults.idleTtlMinutes == 30
    assert defaults.hardTtlMinutes == 120
    assert defaults.runTimeoutSeconds == 30


def testSessionDefaultsExplicitValues() -> None:
    """Verify SessionDefaults with explicit values.

    Returns:
        None
    """
    defaults = SessionDefaults(
        runtime=RuntimeName.PYTHON,
        idleTtlMinutes=60,
        hardTtlMinutes=240,
        runTimeoutSeconds=60,
    )
    assert defaults.idleTtlMinutes == 60
    assert defaults.hardTtlMinutes == 240
    assert defaults.runTimeoutSeconds == 60


# ============================================================================
# SecurityConfig
# ============================================================================


def testSecurityConfigDefaults() -> None:
    """Verify SecurityConfig default values.

    Returns:
        None
    """
    cfg = SecurityConfig()
    assert cfg.user == "1000:1000"
    assert cfg.readOnlyRootfs is True
    assert cfg.noNewPrivileges is True
    assert cfg.dropCapabilities == ("ALL",)
    assert cfg.privileged is False
    assert cfg.envAllowlist == ()


def testSecurityConfigExplicitValues() -> None:
    """Verify SecurityConfig with explicit values.

    Returns:
        None
    """
    cfg = SecurityConfig(
        user="2000:2000",
        readOnlyRootfs=False,
        noNewPrivileges=False,
        dropCapabilities=("NET_RAW", "SYS_ADMIN"),
        privileged=True,
        envAllowlist=("HOME", "PATH"),
    )
    assert cfg.user == "2000:2000"
    assert cfg.readOnlyRootfs is False
    assert cfg.noNewPrivileges is False
    assert cfg.dropCapabilities == ("NET_RAW", "SYS_ADMIN")
    assert cfg.privileged is True
    assert cfg.envAllowlist == ("HOME", "PATH")


# ============================================================================
# ConcurrencyConfig
# ============================================================================


def testConcurrencyConfigDefaults() -> None:
    """Verify ConcurrencyConfig default values.

    Returns:
        None
    """
    cfg = ConcurrencyConfig()
    assert cfg.maxQueuedRunsPerSession == 4
    assert cfg.maxConcurrentRunsGlobal == 8
    assert cfg.globalQueueWaitSeconds == 60


# ============================================================================
# GcConfig
# ============================================================================


def testGcConfigDefaults() -> None:
    """Verify GcConfig default values.

    Returns:
        None
    """
    cfg = GcConfig()
    assert cfg.enabled is True
    assert cfg.intervalSeconds == 60
    assert cfg.orphanContainerRetentionMinutes == 10
    assert cfg.orphanWorkspaceRetentionMinutes == 60
    assert cfg.runRetentionMinutes == 1440


# ============================================================================
# InstallContainerConfig
# ============================================================================


def testInstallContainerConfigDefaults() -> None:
    """Verify InstallContainerConfig default values.

    Returns:
        None
    """
    cfg = InstallContainerConfig()
    assert cfg.timeoutSeconds == 600
    assert cfg.memoryMb == 1024
    assert cfg.pidsLimit == 256


# ============================================================================
# PythonRuntimeConfig
# ============================================================================


def testPythonRuntimeConfigDefaults() -> None:
    """Verify PythonRuntimeConfig default values.

    Returns:
        None
    """
    cfg = PythonRuntimeConfig()
    assert cfg.runImageTag == "gromozeka-sandbox-python:run"
    assert cfg.installImageTag == "gromozeka-sandbox-python:install"
    assert cfg.runDockerfile == "lib/sandbox/runtimes/python/Dockerfile"
    assert cfg.installDockerfile == "lib/sandbox/runtimes/python/Dockerfile.install"
    assert cfg.libMountPath == "/sandbox/libs"


def testPythonRuntimeConfigEnvDefaults() -> None:
    """Verify PythonRuntimeConfig.env includes expected keys.

    Returns:
        None
    """
    cfg = PythonRuntimeConfig()
    assert "PYTHONUNBUFFERED" in cfg.env
    assert cfg.env["PYTHONUNBUFFERED"] == "1"
    assert "PYTHONDONTWRITEBYTECODE" in cfg.env
    assert cfg.env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "MPLBACKEND" in cfg.env
    assert cfg.env["MPLBACKEND"] == "Agg"
    assert "PYTHONPATH" in cfg.env
    assert cfg.env["PYTHONPATH"] == "/sandbox/libs"


def testPythonRuntimeConfigInstallContainer() -> None:
    """Verify PythonRuntimeConfig.installContainer is an InstallContainerConfig.

    Returns:
        None
    """
    cfg = PythonRuntimeConfig()
    assert isinstance(cfg.installContainer, InstallContainerConfig)
    assert cfg.installContainer.timeoutSeconds == 600


def testPythonRuntimeConfigEnvIsIndependent() -> None:
    """Verify that two PythonRuntimeConfig instances have independent env dicts.

    Returns:
        None
    """
    cfg1 = PythonRuntimeConfig()
    cfg2 = PythonRuntimeConfig()
    cfg1.env["FOO"] = "bar"
    assert "FOO" not in cfg2.env


# ============================================================================
# SandboxConfig
# ============================================================================


def testSandboxConfigMinimal() -> None:
    """Verify SandboxConfig with only required storage field.

    Returns:
        None
    """
    cfg = SandboxConfig(storage=StorageConfig(rootDir="/tmp/sandbox"))
    assert cfg.storage.rootDir == "/tmp/sandbox"
    assert isinstance(cfg.backend, BackendConfig)
    assert isinstance(cfg.defaults, SessionDefaults)
    assert isinstance(cfg.limits, ResourceLimits)
    assert isinstance(cfg.security, SecurityConfig)
    assert isinstance(cfg.concurrency, ConcurrencyConfig)
    assert isinstance(cfg.gc, GcConfig)
    assert cfg.runtimes == {}


def testSandboxConfigFullNested() -> None:
    """Verify SandboxConfig with all nested configs explicitly provided.

    Returns:
        None
    """
    storage = StorageConfig(rootDir="/data/sandbox", dirMode=0o755, fileMode=0o644)
    docker = DockerBackendConfig(baseUrl="tcp://localhost:2375", imagePullPolicy="always")
    backend = BackendConfig(name=BackendName.DOCKER, docker=docker)
    defaults = SessionDefaults(idleTtlMinutes=60, hardTtlMinutes=240, runTimeoutSeconds=60)
    limits = ResourceLimits(memoryMb=1024, cpuCount=2.0)
    security = SecurityConfig(user="2000:2000", readOnlyRootfs=False)
    concurrency = ConcurrencyConfig(maxQueuedRunsPerSession=8, maxConcurrentRunsGlobal=16)
    gc = GcConfig(enabled=False, intervalSeconds=120)
    pythonRuntime = PythonRuntimeConfig()
    runtimes = {RuntimeName.PYTHON: pythonRuntime}

    cfg = SandboxConfig(
        storage=storage,
        backend=backend,
        defaults=defaults,
        limits=limits,
        security=security,
        concurrency=concurrency,
        gc=gc,
        runtimes=runtimes,
    )

    assert cfg.storage.rootDir == "/data/sandbox"
    assert cfg.storage.dirMode == 0o755
    assert cfg.backend.docker.baseUrl == "tcp://localhost:2375"
    assert cfg.defaults.idleTtlMinutes == 60
    assert cfg.limits.memoryMb == 1024
    assert cfg.security.user == "2000:2000"
    assert cfg.concurrency.maxConcurrentRunsGlobal == 16
    assert cfg.gc.enabled is False
    assert cfg.runtimes[RuntimeName.PYTHON] is pythonRuntime


def testSandboxConfigRuntimesKeyedByRuntimeName() -> None:
    """Verify SandboxConfig.runtimes is keyed by RuntimeName.

    Returns:
        None
    """
    pythonRuntime = PythonRuntimeConfig()
    cfg = SandboxConfig(
        storage=StorageConfig(rootDir="/tmp/sandbox"),
        runtimes={RuntimeName.PYTHON: pythonRuntime},
    )
    assert RuntimeName.PYTHON in cfg.runtimes
    assert cfg.runtimes[RuntimeName.PYTHON] is pythonRuntime
    assert isinstance(cfg.runtimes[RuntimeName.PYTHON], PythonRuntimeConfig)


def testSandboxConfigRuntimesEmptyByDefault() -> None:
    """Verify SandboxConfig.runtimes defaults to an empty dict.

    Returns:
        None
    """
    cfg = SandboxConfig(storage=StorageConfig(rootDir="/tmp/sandbox"))
    assert cfg.runtimes == {}


def testSandboxConfigIndependentDefaults() -> None:
    """Verify that two SandboxConfig instances have independent mutable defaults.

    Returns:
        None
    """
    cfg1 = SandboxConfig(storage=StorageConfig(rootDir="/a"))
    cfg2 = SandboxConfig(storage=StorageConfig(rootDir="/b"))
    cfg1.runtimes[RuntimeName.PYTHON] = PythonRuntimeConfig()
    assert RuntimeName.PYTHON not in cfg2.runtimes


# ============================================================================
# Package-level re-export
# ============================================================================


def testPackageReExportAllConfigs() -> None:
    """Verify that all config classes are importable from lib.sandbox.

    Returns:
        None
    """
    direct_classes = [
        StorageConfigDirect,
        DockerBackendConfigDirect,
        BackendConfigDirect,
        SessionDefaultsDirect,
        SecurityConfigDirect,
        ConcurrencyConfigDirect,
        GcConfigDirect,
        InstallContainerConfigDirect,
        PythonRuntimeConfigDirect,
        SandboxConfigDirect,
    ]
    package_classes = [
        StorageConfig,
        DockerBackendConfig,
        BackendConfig,
        SessionDefaults,
        SecurityConfig,
        ConcurrencyConfig,
        GcConfig,
        InstallContainerConfig,
        PythonRuntimeConfig,
        SandboxConfig,
    ]
    for direct, pkg in zip(direct_classes, package_classes):
        assert direct is pkg, f"{direct.__name__} from lib.sandbox.config is not the same as from lib.sandbox"
