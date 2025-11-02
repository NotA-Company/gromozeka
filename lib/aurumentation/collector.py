"""Generic collector for golden data testing.

This module implements a generic collector that can work with any httpx-based client
by reading test scenarios from a JSON file and collecting golden data through
global httpx patching.
"""

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar

from lib import utils

from .recorder import GoldenDataRecorder


def substituteEnvVars(value: Any, loadDotenv: bool = True) -> Any:
    """Substitute environment variables in a value.

    Args:
        value: Value that may contain ${VAR_NAME} patterns
        loadDotenv: Should we load environment variables from dotenv file first (Default: True)

    Returns:
        Value with environment variables substituted
    """
    # First - load env variables from dotenv file if needed
    if loadDotenv:
        utils.load_dotenv()
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        return os.getenv(var_name, value)
    elif isinstance(value, dict):
        # Check if this is a nested module/class definition
        if "module" in value and "class" in value:
            # This is a module/class definition, instantiate it
            module_path = value["module"]
            class_name = value["class"]
            init_kwargs = value.get("init_kwargs", {})

            # Recursively substitute env vars in init_kwargs
            substituted_init_kwargs = {k: substituteEnvVars(v, False) for k, v in init_kwargs.items()}

            # Import and instantiate the class
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            return cls(**substituted_init_kwargs)
        else:
            # Regular dict, recursively process
            return {k: substituteEnvVars(v, False) for k, v in value.items()}
    elif isinstance(value, list):
        return [substituteEnvVars(item, False) for item in value]
    return value


def sanitizeFilename(text: str) -> str:
    """Convert text to safe filename."""
    # Replace special characters
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in text)
    # Remove multiple underscores
    while "__" in safe:
        safe = safe.replace("__", "_")
    # Limit length
    return safe[:100].strip("_ ")


async def collectGoldenData(
    scenarios: List[Dict[str, Any]], outputDir: Path, secrets: List[str]  # TODO: Use typed dict
) -> None:
    """
    Collect golden data for multiple scenarios using global httpx patching.

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

            # Record HTTP traffic using global patching
            async with GoldenDataRecorder(secrets=secrets) as recorder:
                # Call the method - httpx is patched globally, so all recordings are recorded
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
    parser = argparse.ArgumentParser(description="Generic Golden Data Collector v2")
    parser.add_argument("--input", required=True, help="Input JSON file with test scenarios")
    parser.add_argument("--output", required=True, help="Output directory for golden data")
    parser.add_argument("--secrets", help="Comma-separated list of environment variables containing secrets")

    args = parser.parse_args()

    # Load scenarios
    with open(args.input) as f:
        scenarios = json.load(f)

    # Get secret values from environment
    secrets = []
    if args.secrets:
        for varName in args.secrets.split(","):
            value = os.getenv(varName.strip())
            if value:
                secrets.append(value)
    else:
        # Default to common API key environment variables
        common_keys = ["OPENWEATHERMAP_API_KEY", "API_KEY", "TOKEN", "SECRET"]
        for key in common_keys:
            value = os.getenv(key)
            if value:
                secrets.append(value)

    # Collect golden data
    await collectGoldenData(scenarios=scenarios, outputDir=Path(args.output), secrets=secrets)

    print("\n✅ Golden data collection complete!")


if __name__ == "__main__":
    asyncio.run(main())
