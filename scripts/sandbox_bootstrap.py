#!/usr/bin/env ./venv/bin/python3
"""Install the starter Python library set into the sandbox lib pool.

Run once on a fresh deployment, or whenever the starter list changes.

Usage:
    ./venv/bin/python3 scripts/sandbox_bootstrap.py
        [--config-dir configs/00-defaults]
        [--config-dir configs/local]
        [--dotenv .env]
        [--packages numpy pandas]
        [--runtime python]
        [--upgrade]
        [--init-storage]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from internal.config.manager import ConfigManager  # noqa: E402
from lib.sandbox.config import SandboxConfig  # noqa: E402
from lib.sandbox.enums import RuntimeName  # noqa: E402
from lib.sandbox.manager import SandboxManager  # noqa: E402
from lib.sandbox.storage import ensureDirectoryLayout  # noqa: E402


def buildConfig(configManager: ConfigManager) -> SandboxConfig:
    """Build a SandboxConfig from the ConfigManager.

    Args:
        configManager: The ConfigManager instance.

    Returns:
        A SandboxConfig loaded from configuration.
    """
    sandboxConfig = configManager.get("sandbox", {})
    return SandboxConfig.fromDict(sandboxConfig)


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
        help="Config directory to load (repeatable).",
    )
    parser.add_argument(
        "--dotenv",
        default=".env",
        help="Path to .env file for environment variables (default: .env).",
    )
    parser.add_argument(
        "--packages",
        action="append",
        default=[],
        help="Packages to install (repeatable; overrides config default).",
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
    return parser.parse_args()


async def main() -> int:
    """Run the bootstrap process.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    args = parseArgs()

    # Convert relative paths to absolute paths
    if args.config_dir:
        args.config_dir = [os.path.abspath(dir_path) for dir_path in args.config_dir]

    # Load configuration
    print("Loading configuration...")
    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=args.config_dir,
        dotEnvFile=args.dotenv,
    )
    config = buildConfig(configManager)

    runtime = RuntimeName(args.runtime)
    rootDir = config.storage.rootDir

    print(f"Bootstrapping sandbox runtime: {runtime.value}")
    print(f"Storage root: {rootDir}")

    # Initialize storage if requested
    if args.init_storage:
        print("Initializing storage directory tree...")
        ensureDirectoryLayout(config.storage)
        print("Storage initialized.")

    # Build packages list from CLI args or config
    if args.packages:
        packagesToInstall = args.packages
    else:
        sandboxConfig = configManager.get("sandbox", {})
        if not isinstance(sandboxConfig, dict):
            sandboxConfig = {}
        bootstrapConfig = sandboxConfig.get("bootstrap", {})
        if not isinstance(bootstrapConfig, dict):
            bootstrapConfig = {}
        packagesToInstall = bootstrapConfig.get("starter-packages", [])

    if not packagesToInstall:
        print("ERROR: No packages to install. Use --packages or configure sandbox.bootstrap.starter-packages")
        return 1

    print(f"\nPackages to install: {len(packagesToInstall)}")
    for pkg in packagesToInstall:
        print(f"  - {pkg}")

    # Initialize SandboxManager
    print("\nInitializing SandboxManager...")
    SandboxManager.injectConfig(config)
    manager = SandboxManager.getInstance()

    # Prepare runtime (build images if needed)
    print(f"Preparing runtime {runtime.value}...")
    prepared = False
    try:
        prepared = await manager.prepareRuntime(runtime)
    except Exception as exc:
        print(f"  WARNING: Could not prepare runtime: {exc}")
        print("  Continuing anyway (images may be pre-built)")

    if prepared:
        print("  Runtime prepared successfully")
    else:
        print("  Runtime already prepared or preparation skipped")

    # Show runtime config info
    runtimeConfig = config.runtimes.get(runtime)
    if runtimeConfig is not None:
        print(f"  Run image: {runtimeConfig.runImageTag}")
        print(f"  Install image: {runtimeConfig.installImageTag}")
        print(f"  Library pool: {config.storage.rootDir}/runtimes/{runtime.value}/libs")

    # Install packages
    print(f"\nInstalling {len(packagesToInstall)} packages...")
    try:
        success = await manager.installRuntimeLibraries(
            packagesToInstall,
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
    print(f"Packages:         {len(packagesToInstall)}")
    print(f"Status:           {'SUCCESS' if success else 'FAILED'}")

    if not success:
        return 1

    print("\nBootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
