#!/usr/bin/env python3
"""
Generic Golden Data Collector v2 for Geocode Maps

This script can collect golden data from ANY httpx-based client.
It reads test scenarios from a JSON file and executes them while
recording all HTTP traffic.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import lib.aurumentation.collector as aurumentationCollector  # noqa: E402
from lib import utils  # noqa: E402
from lib.aurumentation.types import ScenarioDict  # noqa: E402
from tests.lib_ratelimiter import initRateLimiter  # noqa: E402

INPUT_DIR = "input"
OUTPUT_DIR = "data"

# Set up logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def collectGoldenData(scenarios: List[ScenarioDict], outputDir: Path, secrets: List[str]) -> None:
    """
    Collect golden data for multiple scenarios.

    Args:
        scenarios: List of test scenarios to execute
        outputDir: Directory to save golden data
        secrets: List of secret values to mask
    """
    limiter = await initRateLimiter("geocode-map-collector", True)
    limiter.bindQueue("geocode-map", "geocode-map-collector")
    outputDir.mkdir(parents=True, exist_ok=True)

    await aurumentationCollector.collectGoldenData(
        scenarios=scenarios,
        outputDir=outputDir,
        secrets=secrets,
    )

    logger.info("✅ Golden data collection complete for Geocode Map!")
    logger.info(f"Files saved to: {outputDir}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generic Golden Data Collector v2 for Geocode Maps",
        usage="\n"
        "Put Geocode Maps API Key into GEOCODE_MAPS_API_KEY environment variable\n"
        " or into .env file (to preserve it for future) and run it with:\n"
        "./venv/bin/python3 ./tests/geocode_maps/golden/collect.py",
    )
    parser.add_argument("--input", default="scenarios.json", help="Input JSON file with test scenarios")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Output directory for golden data")
    parser.add_argument("--secrets", help="Comma-separated list of environment variables containing secrets")

    args: argparse.Namespace = parser.parse_args()

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
    secrets = ["GEOCODE_MAPS_API_KEY", "API_KEY", "TOKEN", "SECRET"]
    if args.secrets:
        secrets = [varName for varName in args.secrets.split(",")]

    # Check for required environment variables
    if not os.getenv("GEOCODE_MAPS_API_KEY"):
        logger.error("Error: GEOCODE_MAPS_API_KEY environment variable is required")
        sys.exit(1)

    # Collect golden data
    await collectGoldenData(scenarios=scenarios, outputDir=outputPath, secrets=secrets)

    logger.info("\n✅ Golden data collection complete!")


if __name__ == "__main__":
    asyncio.run(main())
