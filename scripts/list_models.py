#!/usr/bin/env ./venv/bin/python3
"""List available models from a remote LLM provider and compare with local config.

Loads the project configuration the same way ``main.py`` does, instantiates
the specified provider, and calls ``listRemoteModels()`` to fetch the remote
model catalogue.  For each model configured locally under this provider, the
script compares the local ``context`` value with the remote ``context_length``
and flags mismatches.

Usage:
    ./venv/bin/python3 scripts/list_models.py --provider NAME [flags]

Flags:
    --config-dir DIR      Directory to load .toml config files from (can be
                          specified multiple times, same as main.py).
                          Default: --config-dir configs/00-defaults
                                   --config-dir configs/local
    --dotenv-file FILE    Path to .env file with env variables for substitute
                          in configs.  Default: .env
    --provider NAME       Provider name to query (required, e.g. 'openrouter',
                          'yc-openai').

Exit codes:
    0  All configured models match remote context sizes (or no models configured).
    1  At least one mismatch or missing model detected.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)

from internal.config.manager import ConfigManager  # noqa: E402
from lib.ai.providers.custom_openai_provider import CustomOpenAIProvider  # noqa: E402
from lib.ai.providers.openrouter_provider import OpenrouterProvider  # noqa: E402
from lib.ai.providers.yc_openai_provider import YcOpenaiProvider  # noqa: E402
from lib.ai.providers.yc_sdk_provider import YcAIProvider  # noqa: E402

_DEFAULT_CONFIG_DIRS: List[str] = ["configs/00-defaults", "configs/local"]

_PROVIDER_TYPES: Dict[str, type] = {
    "yc-openai": YcOpenaiProvider,
    "openrouter": OpenrouterProvider,
    "yc-sdk": YcAIProvider,
    "custom-openai": CustomOpenAIProvider,
}


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="list_models.py",
        description=(
            "List available models from a remote LLM provider and compare "
            "context sizes with the local configuration."
        ),
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
    parser.add_argument(
        "--provider",
        required=True,
        metavar="NAME",
        help="Provider name to query (e.g. 'openrouter', 'yc-openai').",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Dump all available fields for each remote model.",
    )
    return parser


async def main() -> int:
    """Fetch remote model list and compare with local config.

    Returns:
        Integer exit code: 0 if all contexts match, 1 if any mismatch or
        missing model is detected.
    """
    args = buildParser().parse_args()

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS
    print(f"Loading configs from: {', '.join(configDirs)}")

    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=configDirs,
        dotEnvFile=args.dotenv_file,
    )

    modelsConfig: Dict[str, Any] = configManager.getModelsConfig()

    # --- Find the provider in config ---
    providersConfig: Dict[str, Any] = modelsConfig.get("providers", {})
    providerName: str = args.provider

    if providerName not in providersConfig:
        print(f"Provider '{providerName}' not found in config.")
        print(f"Available providers: {', '.join(sorted(providersConfig.keys()))}")
        return 1

    providerConfig: Dict[str, Any] = providersConfig[providerName]
    providerType: str = providerConfig.get("type", providerName)

    # --- Instantiate the provider ---
    ProviderClass = _PROVIDER_TYPES.get(providerType)
    if ProviderClass is None:
        print(f"Unknown provider type: {providerType}")
        print(f"Supported types: {', '.join(sorted(_PROVIDER_TYPES.keys()))}")
        return 1

    print(f"Initializing provider '{providerName}' (type={providerType})...")
    try:
        provider = ProviderClass(providerConfig)
    except Exception as exc:
        print(f"Failed to initialize provider: {exc}")
        return 1

    # --- Fetch remote models ---
    print(f"Fetching models from {providerName}...")
    remoteModels: Dict[str, Dict[str, Any]] = await provider.listRemoteModels()

    if not remoteModels:
        print("No models returned (provider may not support remote listing).")
    else:
        print(f"\nRemote models ({len(remoteModels)} total):")
        print("-" * 80)
        for modelId in sorted(remoteModels.keys()):
            info = remoteModels[modelId]
            print(f"  {modelId}")
            if args.verbose:
                for key in sorted(info.keys()):
                    value = info[key]
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, indent=4)
                    print(f"    {key}: {value}")
            else:
                contextLen = info.get("context_length", "N/A")
                if contextLen != "N/A":
                    print(f"    context_length: {contextLen}")

    # --- Compare with configured models ---
    modelsSection: Dict[str, Any] = modelsConfig.get("models", {})
    configuredModels: Dict[str, Any] = {
        name: cfg for name, cfg in modelsSection.items() if cfg.get("provider") == providerName
    }

    if not configuredModels:
        print("\nNo models configured for this provider.")
        return 0

    print(f"\nConfigured models ({len(configuredModels)}):")
    print("-" * 80)

    mismatches: int = 0
    for modelName, modelCfg in sorted(configuredModels.items()):
        modelId: str = modelCfg.get("model_id", modelName)
        localContext: Any = modelCfg.get("context", "N/A")

        # Try lookup by model_id first, then by the config key name
        remoteInfo: Optional[Dict[str, Any]] = remoteModels.get(modelId) or remoteModels.get(modelName)
        if remoteInfo:
            remoteContext: Any = remoteInfo.get("context_length")
            if remoteContext is not None and localContext != remoteContext:
                status = "MISMATCH"
                mismatches += 1
            else:
                status = "OK"
        else:
            status = "NOT IN REMOTE LIST"
            mismatches += 1

        print(f"  {modelName} ({modelId})")
        print(f"    local context:  {localContext}")
        if remoteInfo:
            print(f"    remote context: {remoteInfo.get('context_length', 'N/A')}")
        else:
            print("    remote context: N/A")
        print(f"    status: {status}")

    print(f"\nMismatches: {mismatches}")
    if mismatches > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
