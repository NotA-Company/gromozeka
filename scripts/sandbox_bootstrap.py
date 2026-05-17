#!/usr/bin/env ./venv/bin/python3
"""Install the starter Python library set into the sandbox lib pool.

Run once on a fresh deployment, or whenever the starter list changes.

Usage:
    ./venv/bin/python3 scripts/sandbox_bootstrap.py
        [--config-dir configs/00-defaults]
        [--config-dir configs/local]
        [--runtime python]
        [--upgrade]
        [--init-storage]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.sandbox.config import PythonRuntimeConfig, SandboxConfig, StorageConfig  # noqa: E402
from lib.sandbox.enums import RuntimeName  # noqa: E402
from lib.sandbox.manager import SandboxManager  # noqa: E402
from lib.sandbox.storage import ensureDirectoryLayout  # noqa: E402


def buildConfig(rootDir: str) -> SandboxConfig:
    """Build a minimal SandboxConfig for bootstrapping.

    Args:
        rootDir: The storage root directory.

    Returns:
        A SandboxConfig with reasonable defaults.
    """
    storage = StorageConfig(rootDir=rootDir)
    pythonRuntime = PythonRuntimeConfig()
    return SandboxConfig(
        storage=storage,
        runtimes={RuntimeName.PYTHON: pythonRuntime},
    )


def parseArgs() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="sandbox-bootstrap.py",
        description="Bootstrap the Gromozeka sandbox library pool.",
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        default=[],
        help="Config directory to load (repeatable). " "If not provided, uses defaults from the library.",
    )
    parser.add_argument(
        "--runtime",
        default="python",
        choices=["python"],
        help="Runtime to bootstrap (default: python).",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade existing packages instead of skipping.",
    )
    parser.add_argument(
        "--init-storage",
        action="store_true",
        help="Create the storage directory tree if it does not exist.",
    )
    parser.add_argument(
        "--root-dir",
        default="/var/lib/gromozeka/sandbox",
        help="Storage root directory (default: /var/lib/gromozeka/sandbox).",
    )
    return parser.parse_args()


async def main() -> int:
    """Run the bootstrap process.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    args = parseArgs()

    rootDir = args.root_dir
    runtime = RuntimeName(args.runtime)

    print(f"Bootstrapping sandbox runtime: {runtime.value}")
    print(f"Storage root: {rootDir}")

    # Build config
    config = buildConfig(rootDir)

    # Initialize storage if requested
    if args.init_storage:
        print("Initializing storage directory tree...")
        ensureDirectoryLayout(config.storage)
        print("Storage initialized.")

    # Build starter packages list
    # These are the default starter packages from the integration design doc §3.1
    starterPackages = [
        "numpy",
        "pandas",
        "matplotlib",
        "scipy",
        "sympy",
        "scikit-learn",
        "pillow",
        "requests",
    ]

    print(f"\nStarter packages to install: {len(starterPackages)}")
    for pkg in starterPackages:
        print(f"  - {pkg}")

    # Initialize SandboxManager
    print("\nInitializing SandboxManager...")
    SandboxManager.injectConfig(config)
    manager = SandboxManager.getInstance()

    # Prepare runtime (build images if needed)
    print(f"Preparing runtime {runtime.value}...")
    try:
        runtimeInfo = await manager.prepareRuntime(runtime)
        print(f"  Run image: {runtimeInfo.runImageTag}")
        print(f"  Install image: {runtimeInfo.installImageTag}")
        print(f"  Library pool: {runtimeInfo.libPoolPath}")
    except Exception as exc:
        print(f"  WARNING: Could not prepare runtime: {exc}")
        print("  Continuing anyway (images may be pre-built)")

    # Install starter packages
    print(f"\nInstalling {len(starterPackages)} packages...")
    try:
        result = await manager.installRuntimeLibraries(
            starterPackages,
            runtime=runtime,
            upgrade=args.upgrade,
        )
    except Exception as exc:
        print(f"ERROR: Install failed: {exc}")
        return 1

    # Print summary
    print("\n" + "=" * 60)
    print("BOOTSTRAP SUMMARY")
    print("=" * 60)
    print(f"Runtime:          {runtime.value}")
    print(f"Pool version:     {result.poolVersion}")
    print(f"Installed:        {len(result.installed)}")
    print(f"Skipped:          {len(result.skipped)}")
    print(f"Failed:           {len(result.failed)}")

    if result.skipped:
        print("\nSkipped packages:")
        for pkg in result.skipped:
            print(f"  - {pkg}")

    if result.failed:
        print("\nFailed packages:")
        for pkg, reason in result.failed:
            print(f"  - {pkg}: {reason}")

    if result.failed:
        return 1

    print("\nBootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
