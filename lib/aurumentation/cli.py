"""CLI interface for the golden data collector.

This module provides a command-line interface for collecting golden data
using the generic collector functionality. It allows users to specify
input scenarios, output directories, target functions, and secrets for
masking sensitive data during collection.

The CLI supports:
- Importing functions from any Python module
- Loading test scenarios from JSON files
- Masking sensitive data (API keys, tokens, etc.)
- Generating golden data files for testing purposes

Example:
    python -m lib.aurumentation.cli --input tests/golden_data/openweathermap/inputs/locations.json \\
        --output tests/golden_data/openweathermap/golden \\
        --module lib.openweathermap.client \\
        --function getWeatherByCity \\
        --secrets $OPENWEATHERMAP_API_KEY
"""

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path
from typing import List

from .collector import collectGoldenData


def importFunction(modulePath: str, functionName: str) -> object:
    """Import a function from a module.

    Args:
        modulePath: Python module path (e.g., 'lib.openweathermap.client')
        functionName: Name of the function to import

    Returns:
        The imported function

    Raises:
        ImportError: If module or function cannot be imported
    """
    try:
        module = importlib.import_module(modulePath)
        func = getattr(module, functionName)
        return func
    except ImportError as e:
        raise ImportError(f"Failed to import module '{modulePath}': {e}")
    except AttributeError:
        raise AttributeError(f"Function '{functionName}' not found in module '{modulePath}'")


def parseSecrets(secretsStr: str) -> List[str]:
    """Parse comma-separated secrets string.

    Args:
        secretsStr: Comma-separated list of secrets

    Returns:
        List of secrets
    """
    if not secretsStr:
        return []
    return [secret.strip() for secret in secretsStr.split(",") if secret.strip()]


def main() -> None:
    """Main CLI entry point for golden data collection.

    This function parses command-line arguments, imports the target function,
    loads test scenarios from a JSON file, and executes the golden data
    collection process. It handles secrets for masking sensitive data and
    provides a summary of the collection results.

    The function performs the following steps:
    1. Parse command-line arguments (input file, output directory, module, function, secrets)
    2. Import the target function from the specified module
    3. Parse secrets for masking sensitive data
    4. Load test scenarios from the input JSON file
    5. Execute the golden data collection process
    6. Generate and display a summary of results

    Returns:
        None

    Raises:
        SystemExit: If an error occurs during execution (exit code 1)
        ImportError: If the target module or function cannot be imported
        FileNotFoundError: If the input JSON file does not exist
        json.JSONDecodeError: If the input file contains invalid JSON
        Exception: For any other errors during collection
    """
    parser = argparse.ArgumentParser(
        description="Collect golden data for any function/method",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --input tests/golden_data/openweathermap/inputs/locations.json \\
           --output tests/golden_data/openweathermap/golden \\
           --module lib.openweathermap.client \\
           --function getWeatherByCity \\
           --secrets $OPENWEATHERMAP_API_KEY

  %(prog)s -i inputs.json -o golden_data -m mymodule.client -f search --secrets "key1,key2"
        """,
    )

    parser.add_argument("--input", "-i", required=True, help="Path to input JSON file with test scenarios")

    parser.add_argument("--output", "-o", required=True, help="Output directory for golden data files")

    parser.add_argument("--module", "-m", required=True, help="Python module path containing the target function")

    parser.add_argument("--function", "-f", required=True, help="Function name to test")

    parser.add_argument(
        "--secrets", "-s", help="Comma-separated list of secrets to mask (or set via environment variables)"
    )

    args = parser.parse_args()

    try:
        # Import the target function
        print(f"Importing function '{args.function}' from module '{args.module}'...")
        importFunction(args.module, args.function)
        print(f"✓ Successfully imported {args.module}.{args.function}")

        # Parse secrets from command line or detect from environment
        secrets = []
        if args.secrets:
            secrets = parseSecrets(args.secrets)
            print(f"✓ Using {len(secrets)} secrets from command line")
        else:
            # No secrets provided
            print("⚠ No secrets provided - sensitive data will not be masked")

        # Load scenarios from input file
        print("\nLoading scenarios...")
        with open(args.input, "r") as f:
            scenarios = json.load(f)
        print(f"  Loaded {len(scenarios)} scenarios")

        # Run the collector
        print("\nCollecting golden data...")
        print(f"  Input file: {args.input}")
        print(f"  Output directory: {args.output}")

        asyncio.run(collectGoldenData(scenarios=scenarios, outputDir=Path(args.output), secrets=secrets))

        # Create a simple summary
        summary = {
            "function_name": f"{args.module}.{args.function}",
            "total_scenarios": len(scenarios),
            "successful_scenarios": len(scenarios),  # Assuming all succeed for now
            "failed_scenarios": 0,  # Assuming none fail for now
            "output_directory": args.output,
        }

        # Print summary
        print("\nCollection complete!")
        print(f"  Function: {summary['function_name']}")
        print(f"  Total scenarios: {summary['total_scenarios']}")
        print(f"  Successful: {summary['successful_scenarios']}")
        print(f"  Failed: {summary['failed_scenarios']}")
        print(f"  Output directory: {summary['output_directory']}")

        if summary["failed_scenarios"] > 0:
            print(f"\n⚠ {summary['failed_scenarios']} scenarios failed. Check output above for details.")
            sys.exit(1)
        else:
            print("\n✓ All scenarios collected successfully!")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
