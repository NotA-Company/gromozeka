#!/usr/bin/env ./venv/bin/python3
"""Simple demonstration of aiodocker usage.

Lists Docker images, containers, and shows Docker daemon version.
Useful for verifying Docker connectivity and exploring aiodocker API.

Usage:
    ./venv/bin/python3 scripts/aiodocker_demo.py [--all] [--url DOCKER_HOST]

Flags:
    --all        List all containers (including stopped ones).
    --url URL    Docker daemon URL (default: unix://var/run/docker.sock).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import argparse  # noqa: E402
import logging  # noqa: E402

import aiodocker  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def getDockerVersion(client: aiodocker.Docker) -> dict[str, Any]:
    """Fetch Docker daemon version information.

    Args:
        client: Connected aiodocker client.

    Returns:
        Dictionary with version details.

    Raises:
        aiodocker.DockerError: If the version call fails.
    """
    versionInfo = await client.version()
    return versionInfo


async def listImages(client: aiodocker.Docker) -> None:
    """List all Docker images on the host.

    Args:
        client: Connected aiodocker client.
    """
    images = await client.images.list()
    print(any(["alpine:3.23" in v.get("RepoTags", []) for v in images]))
    if not images:
        print("No images found.")
        return

    print(f"Found {len(images)} image(s):")
    for img in images:
        repoTags = img.get("RepoTags", ["<none>:<none>"])
        imageId = img.get("Id", "unknown")[:12]
        size = img.get("Size", 0)
        humanSize = f"{size / (1024 ** 2):.1f} MB" if size else "unknown"
        print(f"  {imageId}  {', '.join(repoTags)}  ({humanSize})")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="aiodocker demonstration script")
    parser.add_argument(
        "--all",
        action="store_true",
        help="List all containers (including stopped)",
    )
    parser.add_argument(
        "--url",
        default="unix://var/run/docker.sock",
        help="Docker daemon URL (default: unix://var/run/docker.sock)",
    )
    args = parser.parse_args()

    client: aiodocker.Docker | None = None
    try:
        client = aiodocker.Docker(url=args.url)
        # Test connection
        versionInfo = await getDockerVersion(client)
        print(f"Docker daemon version: {versionInfo.get('Version', 'unknown')}")
        print(f"API version: {versionInfo.get('ApiVersion', 'unknown')}")
        print()

        await listImages(client)
        print()

        # await listContainers(client, allContainers=args.all)
        # print()

    except aiodocker.DockerError as exc:
        logger.error("Docker error: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        sys.exit(1)
    finally:
        if client is not None:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
