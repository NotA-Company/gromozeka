"""Language runtime implementations for sandboxed code execution.

This package provides a protocol and concrete implementations for executing code
in different language runtimes within sandboxed containers. Each runtime implements
a common interface that allows :class:`SandboxManager` to construct execution
commands, manage dependencies, and detect output artifacts without knowing the
concrete runtime implementation.

Core Components:
    Runtime: Abstract base class defining the protocol that all language runtimes
        must implement. This includes methods for building run commands, package
        management commands, and parsing their output.

Subpackages:
    python: Concrete runtime implementation for executing Python code, including
        pip-based package management and artifact detection.

Usage:
    The runtimes package is typically used by importing specific runtime implementations::

        from lib.sandbox.runtimes.python import PythonRuntime
        from lib.sandbox.config import BasicRuntimeConfig

        config = BasicRuntimeConfig(...)
        runtime = PythonRuntime(config)

    The :class:`Runtime` protocol can be used for type hints when working with
    any runtime implementation::

        from lib.sandbox.runtimes.base import Runtime

        def prepareRuntime(runtime: Runtime) -> None:
            # Work with any runtime implementation
            pass

Supported Runtimes:
    Python (See :mod:`lib.sandbox.runtimes.python`)
"""

from .base import Runtime

__all__ = ["Runtime"]
