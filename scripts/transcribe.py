#!/usr/bin/env ./venv/bin/python3
"""Transcribe an audio or video file using the configured STT provider.

Loads the project configuration the same way ``main.py`` does, constructs the
configured STT provider directly via ``lib.stt`` (bypassing the bot-oriented
admission pipeline — rate limiters, concurrency semaphore), and transcribes
the given media file.  The formatted transcript is printed to stdout.

Usage:
    ./venv/bin/python3 scripts/transcribe.py [flags] MEDIA_FILE

Flags:
    MEDIA_FILE              Path to the audio or video file to transcribe
                            (required).
    --config-dir DIR        Directory to load .toml config files from (can be
                            specified multiple times, same as main.py).
                            Default: --config-dir configs/00-defaults
                                     --config-dir configs/local
    --dotenv-file FILE      Path to .env file with env variables for substitute
                            in configs.  Default: .env

Exit codes:
    0  Transcription succeeded (or no speech detected).
    1  Any error (STT disabled, provider init failure, transcription error).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import argparse  # noqa: E402
import asyncio  # noqa: E402
import logging  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.ERROR)

import httpx2  # noqa: E402

# Process-wide: make `import httpx` resolve to `httpx2` so third-party clients
# used by project code (sqlink's transport via lib.db.providers, the openai SDK
# via lib.ai providers) share the bot's httpx2 stack. MUST run before the
# first project import below: internal.* / lib.* modules transitively perform
# a real `import httpx`, after which scripts._lib.bootstrap's module-level
# alias_httpx() would raise RuntimeError. The call is idempotent, so
# bootstrap's later repeat invocation is a no-op. House pattern: main.py:16-37;
# background: docs/design/httpx2-migration-v1.md §6.
httpx2.alias_httpx()

import lib.utils as libUtils  # noqa: E402
from internal.config.manager import ConfigManager  # noqa: E402
from internal.services.proxy.service import ProxyService  # noqa: E402
from internal.services.stt.formatter import formatTranscript  # noqa: E402
from internal.services.stt.service import STT_PROVIDERS_MAP  # noqa: E402
from lib.stt import STTResultStatus  # noqa: E402
from lib.stt.abstract import AbstractSTTProvider  # noqa: E402
from scripts._lib.bootstrap import bootstrapProxy  # noqa: E402

_DEFAULT_CONFIG_DIRS: List[str] = ["configs/00-defaults", "configs/local"]


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="transcribe.py",
        description="Transcribe an audio or video file using the configured STT provider.",
    )
    parser.add_argument(
        "mediaFile",
        metavar="MEDIA_FILE",
        help="Path to the audio or video file to transcribe.",
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        dest="configDirs",
        metavar="DIR",
        help=(
            "Directory to load .toml config files from (can be specified multiple times). "
            f"Default: {' '.join('--config-dir ' + d for d in _DEFAULT_CONFIG_DIRS)}"
        ),
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file with env variables for substitute in configs",
    )
    return parser


async def main() -> int:
    """Transcribe the given media file and print the transcript to stdout.

    Returns:
        Integer exit code: 0 on success, 1 on any error.
    """
    args = buildParser().parse_args()

    mediaPath = Path(args.mediaFile)
    if not mediaPath.is_file():
        print(f"Error: file not found: {args.mediaFile}", file=sys.stderr)
        return 1

    data: bytes = mediaPath.read_bytes()

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS

    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=configDirs,
        dotEnvFile=args.dotenv_file,
    )

    bootstrapProxy(configManager)

    sttConfig: Dict[str, Any] = configManager.getSttConfig()
    enabled: bool = bool(sttConfig.get("enabled", False))

    if not enabled:
        print("Error: STT is disabled (stt.enabled = false).", file=sys.stderr)
        return 1

    providerName: str = str(sttConfig.get("provider", ""))
    if providerName not in STT_PROVIDERS_MAP:
        print(f"Error: unknown STT provider '{providerName}'.", file=sys.stderr)
        return 1

    proxyConfig = ProxyService.getInstance().resolveProxy(sttConfig, "stt")

    providerKwargs = {
        libUtils.kebabToCamelCase(k): v
        for k, v in sttConfig.items()
        if k
        not in (
            "enabled",
            "use-proxy",
            "proxy-config",
            "provider",
            "max-source-bytes",
            "chat-ratelimiter-queue",
            "global-ratelimiter-queue",
            "max-concurrency",
        )
    }

    provider: AbstractSTTProvider = STT_PROVIDERS_MAP[providerName](
        proxyConfig=proxyConfig,
        **providerKwargs,
    )

    try:
        result = await provider.stt(data)

        if result.status == STTResultStatus.ERROR:
            errorCode = result.errorCode or "unknown"
            print(f"Error: transcription failed ({errorCode}).", file=sys.stderr)
            return 1

        transcript = formatTranscript(result)
        if transcript:
            print(transcript)

        return 0
    finally:
        await provider.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
