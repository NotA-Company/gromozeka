"""Enumeration classes for sandboxed code execution.

This module defines string-based enumerations used throughout the sandbox library
for identifying runtime environments, execution backends, and run statuses.
All enums inherit from StrEnum to ensure string representation and comparison capabilities.

Enums:
    RuntimeName: Identifies the programming language runtime for sandboxed execution.
    BackendName: Identifies the execution backend that runs sandboxed code.
    RunStatus: Describes the status of a sandboxed code execution run.
"""

from enum import StrEnum


class RuntimeName(StrEnum):
    """Runtime name enumeration for sandboxed code execution environments.

    Identifies the programming language runtime in which sandboxed code
    will be executed.
    """

    # Python runtime environment for executing Python code in sandboxed containers.
    PYTHON = "python"


class BackendName(StrEnum):
    """Backend name enumeration for sandboxed code execution backends.

    Identifies the execution backend responsible for running sandboxed code.
    """

    # Docker container-based execution backend for running code in isolated containers.
    DOCKER = "docker"


class RunStatus(StrEnum):
    """Run status enumeration for sandboxed code execution.

    Describes the current state of a single code execution run.
    """

    # The run is currently in progress and has not yet completed.
    RUNNING = "running"
    # The run finished successfully without errors.
    COMPLETED = "completed"
    # The run failed or was terminated abnormally.
    FAILED = "failed"
