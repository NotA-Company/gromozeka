#!/usr/bin/env python3
"""
AI Providers Golden Data Collector

This script collects golden data from AI providers by executing test scenarios
and recording all HTTP traffic. It supports multiple providers:
- BasicOpenAIProvider (OpenAI-compatible APIs)
- YcOpenaiProvider (Yandex Cloud OpenAI-compatible)
- OpenrouterProvider (OpenRouter aggregation service)
- YcSdkProvider (Yandex Cloud SDK - special handling required)

The script reads scenario definitions from JSON files and saves recorded
HTTP traffic with secrets masked for safe storage and replay.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

import openai._base_client

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib import utils  # noqa: E402
from lib.aurumentation.collector import collectGoldenData  # noqa: E402
from lib.aurumentation.recorder import GoldenDataRecorder  # noqa: E402
from lib.aurumentation.types import ScenarioDict  # noqa: E402

# Directory structure
INPUT_DIR = "input"
OUTPUT_DIR = "data"

# Provider-specific constants
PROVIDERS = {
    "yc_openai": {"scenario_file": "yc_openai_scenarios.json", "description": "Yandex Cloud OpenAI Provider"},
    "openrouter": {"scenario_file": "openrouter_scenarios.json", "description": "OpenRouter Provider"},
    "yc_sdk": {"scenario_file": "yc_sdk_scenarios.json", "description": "Yandex Cloud SDK Provider"},
}

# Environment variables for each provider
PROVIDER_ENV_VARS = {
    "yc_openai": ["YC_API_KEY", "YC_FOLDER_ID"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "yc_sdk": ["YC_PROFILE", "YC_FOLDER_ID"],
}

# Set up logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class OpenAIRecorderPatcher:
    def __init__(self):
        self.originalOpenAIClientClass: Optional[type] = None
        self.openaiClientClass: Optional[type] = None

    async def patchOpenAI(self, recorder: GoldenDataRecorder) -> None:
        # Also patch OpenAI's AsyncHttpxClientWrapper if it exists
        try:

            class PatchedOpenAIClient(openai._base_client.AsyncHttpxClientWrapper):
                def __init__(self, *args, **kwargs):
                    logger.info("Patching openai.AsyncHttpxClientWrapper...")
                    # Force our transport to be used
                    kwargs["transport"] = recorder.transport
                    super().__init__(*args, **kwargs)

            self.originalOpenAIClientClass = openai._base_client.AsyncHttpxClientWrapper
            self.openaiClientClass = PatchedOpenAIClient
            # Patch the class in the openai module
            openai._base_client.AsyncHttpxClientWrapper = PatchedOpenAIClient
            logger.info("HttpxRecorder: Patched openai.AsyncHttpxClientWrapper")
        except Exception as e:
            logger.error("HttpxRecorder: OpenAI patch failed, skipping OpenAI client patching")
            logger.exception(e)
            if self.originalOpenAIClientClass is not None:
                openai._base_client.AsyncHttpxClientWrapper = self.originalOpenAIClientClass
            self.originalOpenAIClientClass = None
            self.openaiClientClass = None

    async def unpatchOpenAI(self, recorder: GoldenDataRecorder) -> None:
        if self.openaiClientClass is not None:
            openai._base_client.AsyncHttpxClientWrapper = self.originalOpenAIClientClass
            self.originalOpenAIClientClass = None
            self.openaiClientClass = None
            logger.info("HttpxRecorder: Unpatched openai.AsyncHttpxClientWrapper")


def getAllSecrets() -> List[str]:
    """
    Get secret values for a provider from environment variables.

    Args:
        providerName: Name of the provider

    Returns:
        List of secret values to mask
    """

    secrets = []

    for providerName in PROVIDER_ENV_VARS:
        secrets.extend(PROVIDER_ENV_VARS[providerName])

    return secrets


def checkRequiredEnvVars(providerName: str) -> bool:
    """
    Check if required environment variables are set for a provider.

    Args:
        providerName: Name of the provider

    Returns:
        True if all required variables are set, False otherwise
    """
    if providerName not in PROVIDER_ENV_VARS:
        logger.error(f"Unknown provider: {providerName}")
        return False

    missingVars = []
    for varName in PROVIDER_ENV_VARS[providerName]:
        if not os.getenv(varName):
            missingVars.append(varName)

    if missingVars:
        logger.error(f"Missing required environment variables for {providerName}: {', '.join(missingVars)}")
        return False

    return True


async def collectProviderData(providerName: str, outputDir: Optional[Path] = None) -> None:
    """
    Collect golden data for a specific provider.

    Args:
        providerName: Name of the provider to collect data for
        outputDir: Output directory (optional, defaults to provider-specific dir)
    """
    if providerName not in PROVIDERS:
        raise ValueError(f"Unknown provider: {providerName}")

    providerInfo = PROVIDERS[providerName]
    logger.info(f"Collecting golden data for {providerInfo['description']}")

    # Check required environment variables
    if not checkRequiredEnvVars(providerName):
        raise EnvironmentError(f"Required environment variables not set for {providerName}")

    # Resolve paths
    scriptDir = Path(__file__).parent
    inputPath = scriptDir / INPUT_DIR / providerInfo["scenario_file"]
    outputPath = outputDir or (scriptDir / OUTPUT_DIR)

    # Check if scenario file exists
    if not inputPath.exists():
        raise FileNotFoundError(f"Scenario file not found: {inputPath}")

    # Load scenarios
    logger.info(f"Loading scenarios from {inputPath}")
    with open(inputPath) as f:
        scenarios: List[ScenarioDict] = json.load(f)

    logger.info(f"Loaded {len(scenarios)} scenarios")

    # Get secrets for masking
    secrets = getAllSecrets()
    logger.info(f"Using {len(secrets)} secrets for masking")

    # Collect golden data
    logger.info("Starting data collection...")
    openAiPatcher = OpenAIRecorderPatcher()
    await collectGoldenData(
        scenarios=scenarios,
        outputDir=outputPath,
        secrets=secrets,
        aenterCallback=openAiPatcher.patchOpenAI,
        aexitCallback=openAiPatcher.unpatchOpenAI,
    )

    logger.info(f"✅ Golden data collection complete for {providerName}!")
    logger.info(f"Files saved to: {outputPath}")


async def collectAllProviders(outputDir: Optional[Path] = None) -> None:
    """
    Collect golden data for all providers.

    Args:
        outputDir: Base output directory (optional)
    """
    logger.info("Collecting golden data for all providers")

    # HTTP-based providers that can use standard collection
    httpProviders = ["yc_openai", "openrouter", "yc_sdk"]

    for providerName in httpProviders:
        try:
            await collectProviderData(providerName, outputDir)
            logger.info(f"✓ Completed {providerName}")
        except Exception as e:
            logger.error(f"✗ Failed to collect data for {providerName}: {e}")
            continue


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI Providers Golden Data Collector",
        usage="""
Collect golden data for AI providers. Set required environment variables before running.

Required environment variables:
  OPENAI_API_KEY          - For BasicOpenAIProvider
  YC_API_KEY, YC_FOLDER_ID - For YcOpenaiProvider
  OPENROUTER_API_KEY      - For OpenrouterProvider
  YC_PROFILE, YC_FOLDER_ID - For YcSdkProvider

Examples:
  # Collect for specific provider
  ./venv/bin/python3 tests/lib-ai/ai_providers/collect.py --provider basic_openai

  # Collect for all providers
  ./venv/bin/python3 tests/lib-ai/ai_providers/collect.py --all

  # Collect with custom output directory
  ./venv/bin/python3 tests/lib-ai/ai_providers/collect.py --provider basic_openai --output-dir /tmp/golden-data
        """,
    )
    parser.add_argument(
        "--provider", choices=["yc_openai", "openrouter", "yc_sdk"], help="Collect golden data for specific provider"
    )
    parser.add_argument("--all", action="store_true", help="Collect golden data for all providers")
    parser.add_argument(
        "--output-dir", help="Output directory for golden data (default: data/ in provider subdirectories)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.provider and not args.all:
        parser.error("Either --provider or --all must be specified")

    if args.provider and args.all:
        parser.error("--provider and --all cannot be used together")

    # Parse output directory
    outputDir = Path(args.output_dir) if args.output_dir else None

    # Load environment variables
    utils.load_dotenv()

    try:
        if args.all:
            await collectAllProviders(outputDir)
        else:
            await collectProviderData(args.provider, outputDir)

        print("\n🎉 Golden data collection complete!")

    except Exception as e:
        logger.error(f"Collection failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
