#!/usr/bin/env python3
"""
Generic Golden Data Collector v2 for Yandex Search

This script can collect golden data from ANY httpx-based client.
It reads test scenarios from a JSON file and executes them while
recording all HTTP traffic.
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from typing import List

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib import utils  # noqa: E402
from lib.aurumentation.collector import substituteEnvVars  # noqa: E402
from lib.aurumentation.recorder import GoldenDataRecorder  # noqa: E402
from lib.aurumentation.types import ScenarioDict  # noqa: E402
from lib.aurumentation.collector import sanitizeFilename  # noqa: E402

INPUT_DIR = "input"
OUTPUT_DIR = "data"


async def collectGoldenData(scenarios: List[ScenarioDict], outputDir: Path, secrets: List[str]) -> None:
    """
    Collect golden data for multiple scenarios.

    Args:
        scenarios: List of test scenarios to execute
        outputDir: Directory to save golden data
        secrets: List of secret values to mask
    """
    outputDir.mkdir(parents=True, exist_ok=True)

    for scenario in scenarios:
        print(f"Collecting: {scenario['description']}")

        try:
            # Extract scenario details
            modulePath = scenario["module"]
            className = scenario["class"]
            methodName = scenario["method"]
            kwargs = scenario["kwargs"]
            initKwargs = scenario.get("init_kwargs", {})
            description = scenario["description"]

            # Substitute environment variables in init_kwargs
            substitutedInitKwargs = {k: substituteEnvVars(v) for k, v in initKwargs.items()}

            # Import and instantiate class
            module = importlib.import_module(modulePath)
            cls = getattr(module, className)
            instance = cls(**substitutedInitKwargs)

            # Record HTTP traffic
            async with GoldenDataRecorder(secrets=secrets) as recorder:
                # Call the method
                method = getattr(instance, methodName)
                if asyncio.iscoroutinefunction(method):
                    result = await method(**kwargs)
                else:
                    result = method(**kwargs)

                # Generate filename from description
                filename = sanitizeFilename(description) + ".json"
                filepath = outputDir / filename

                # Get recordings before saving
                calls = recorder.getRecordedRecordings()
                print(f"Saving {len(calls)} recordings")

                # Save golden data
                recorder.saveGoldenData(
                    filepath=str(filepath),
                    metadata={
                        "description": description,
                        "module": modulePath,
                        "class": className,
                        "method": methodName,
                        "init_kwargs": initKwargs,  # Store original (with ${VAR} placeholders)
                        "kwargs": kwargs,
                        "result_type": type(result).__name__,
                    },
                )

                print(f"  ✓ Saved to {filename}")

        except Exception as e:
            print(f"  ✗ Failed to collect scenario '{scenario['description']}': {e}")
            continue


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generic Golden Data Collector v2 for Yandex Search",
        usage="\n"
        "Put Yandex Search API Key into YANDEX_SEARCH_API_KEY environment variable\n"
        " and folder ID into YANDEX_SEARCH_FOLDER_ID environment variable\n"
        " or into .env file (to preserve it for future) and run it with:\n"
        "./venv/bin/python3 ./tests/yandex_search/golden/collect.py",
    )
    parser.add_argument("--input", default="scenarios.json", help="Input JSON file with test scenarios")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Output directory for golden data")
    parser.add_argument("--secrets", help="Comma-separated list of environment variables containing secrets")

    args = parser.parse_args()

    # Resolve paths
    scriptDir = Path(__file__).parent
    inputPath = scriptDir / INPUT_DIR / args.input
    outputPath = scriptDir / args.output

    scenarios: List[ScenarioDict] = []

    # Load scenarios
    with open(inputPath) as f:
        scenarios = json.load(f)

    # Get secret values from environment
    utils.load_dotenv()
    secrets = []
    if args.secrets:
        for varName in args.secrets.split(","):
            value = os.getenv(varName.strip())
            if value:
                secrets.append(value)
    else:
        # Default to Yandex Search API key and folder ID environment variables
        common_keys = ["YANDEX_SEARCH_API_KEY", "YANDEX_SEARCH_FOLDER_ID", "API_KEY", "TOKEN", "SECRET"]
        for key in common_keys:
            value = os.getenv(key)
            if value:
                secrets.append(value)

    # Check for required environment variables
    if not os.getenv("YANDEX_SEARCH_API_KEY"):
        print("Error: YANDEX_SEARCH_API_KEY environment variable is required")
        sys.exit(1)
        
    if not os.getenv("YANDEX_SEARCH_FOLDER_ID"):
        print("Error: YANDEX_SEARCH_FOLDER_ID environment variable is required")
        sys.exit(1)

    # Collect golden data
    await collectGoldenData(scenarios=scenarios, outputDir=outputPath, secrets=secrets)

    print("\n✅ Golden data collection complete!")


if __name__ == "__main__":
    asyncio.run(main())