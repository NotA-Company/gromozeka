"""Golden Data Provider for replaying recorded HTTP recordings.

This module implements a provider that can load golden data scenarios from JSON files
and create httpx clients that replay recorded responses during testing.
"""

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from .replayer import GoldenDataReplayer
from .types import GoldenDataFormat, GoldenDataScenarioDict, HttpCallDict


class GoldenDataProvider:
    """Provider for loading and replaying golden data scenarios.

    This class loads golden data scenarios from JSON files and provides
    methods to create httpx clients that replay recorded HTTP responses.
    """

    def __init__(self, goldenDataDir: str):
        """Initialize the GoldenDataProvider with a directory containing golden data files.

        Args:
            goldenDataDir: Path to directory containing golden data JSON files
        """
        self.goldenDataDir = Path(goldenDataDir)
        self.scenarios: Dict[str, GoldenDataScenarioDict] = {}
        self.replayers: Dict[str | None, GoldenDataReplayer] = {}
        self.usedScenarios: set = set()

        # Scenario with All known recordings (for those, who do not want to care about scenarios)
        # Metadata will be filled with first scenario data (Because nobody care)
        self.metaScenario: Optional[GoldenDataScenarioDict] = None

    def loadScenario(self, filename: str) -> "GoldenDataScenarioDict":
        """Load a specific scenario file.

        Args:
            filename: Name of the JSON file to load (with or without .json extension)

        Returns:
            Loaded GoldenDataScenarioDict object

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file content is invalid
        """
        # Handle filename with or without .json extension
        if not filename.endswith(".json"):
            raise ValueError("Only json files allowed")

        # Handle scenario names with directory paths
        filepath = self.goldenDataDir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Golden data file not found: {filepath}")

        scenario = loadGoldenData(str(filepath))
        # Use the relative path from goldenDataDir as the scenario name
        scenarioName = filename[:-5]  # Remove .json extension
        self.scenarios[scenarioName] = scenario

        if self.metaScenario is None:
            self.metaScenario = copy.deepcopy(scenario)
        else:
            self.metaScenario["recordings"].extend(scenario["recordings"])

        return scenario

    def loadAllScenarios(self) -> Dict[str, "GoldenDataScenarioDict"]:
        """Load all scenarios from the golden data directory.

        Returns:
            Dictionary mapping scenario names to GoldenDataScenarioDict objects
        """
        self.scenarios.clear()

        files = findGoldenDataFiles(str(self.goldenDataDir))
        for filepath in files:
            try:
                # Get relative path from golden data directory
                relPath = os.path.relpath(filepath, str(self.goldenDataDir))
                self.loadScenario(relPath)
            except Exception as e:
                # Log error but continue loading other files
                print(f"Warning: Failed to load golden data file {filepath}: {e}")

        return self.scenarios

    def getScenario(self, name: Optional[str]) -> "GoldenDataScenarioDict":
        """Get a loaded scenario by name.

        Args:
            name: Name of the scenario to retrieve

        Returns:
            GoldenDataScenarioDict object

        Raises:
            KeyError: If scenario is not loaded
        """
        if name is None:
            if self.metaScenario is None:
                raise ValueError("No scenarios loaded")
            return self.metaScenario

        if name not in self.scenarios:
            raise KeyError(f"Scenario '{name}' not loaded. Call loadScenario() or loadAllScenarios() first.")

        self.usedScenarios.add(name)
        return self.scenarios[name]

    def createClient(self, scenarioName: Optional[str]) -> httpx.AsyncClient:
        """Create an httpx client that replays the specified scenario.

        Args:
            scenarioName: Name of the scenario to replay

        Returns:
            httpx.AsyncClient configured to replay the scenario
        """
        scenario = self.getScenario(scenarioName)

        # Create replayer if it doesn't exist
        if scenarioName not in self.replayers:
            self.replayers[scenarioName] = GoldenDataReplayer(scenario)

        replayer = self.replayers[scenarioName]
        return replayer.createClient()

    def __enter__(self):
        """Enter synchronous context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit synchronous context manager."""
        # Clean up resources if needed
        pass

    async def __aenter__(self):
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context manager."""
        # Clean up resources if needed
        pass


def loadGoldenData(filepath: str) -> "GoldenDataScenarioDict":
    """Load and parse a single golden data JSON file.

    Args:
        filepath: Path to the JSON file to load

    Returns:
        GoldenDataScenarioDict object with the loaded data

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file content is invalid or doesn't match expected structure
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Golden data file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data: GoldenDataFormat = json.load(f)

    # Check if this is the new format with metadata and recordings
    if isinstance(data, dict) and "metadata" in data and "recordings" in data:
        # New format - extract metadata and recordings
        metadata = data["metadata"]
        recordings_data = data["recordings"]

        # Convert recordings data to HttpCallDict objects
        recordings: List[HttpCallDict] = []
        for call_data in recordings_data:
            # Convert timestamp string to datetime
            timestamp_str = call_data.get("timestamp", "")
            if timestamp_str:
                try:
                    # Handle different timestamp formats
                    if "+" in timestamp_str or "Z" in timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    else:
                        timestamp = datetime.fromisoformat(timestamp_str)
                except ValueError:
                    # Fallback to current time if parsing fails
                    timestamp = datetime.now(timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            # Create HttpCallDict object
            call: HttpCallDict = {
                "request": call_data["request"],
                "response": call_data["response"],
                "timestamp": timestamp.isoformat(),
            }
            recordings.append(call)

        # Create scenario with metadata
        scenario: GoldenDataScenarioDict = {
            "description": metadata.get("description", "Unknown scenario"),
            "functionName": f"{metadata.get('class', 'Unknown')}.{metadata.get('method', 'unknown')}",
            "metadata": metadata,
            "recordings": recordings,
            "createdAt": (metadata["createdAt"] if "createdAt" in metadata else datetime.now(timezone.utc).isoformat()),
        }

        return scenario

    else:
        raise ValueError(f"Invalid golden data format in {filepath}: expected dict with metadata/recordings")


def findGoldenDataFiles(directory: str) -> List[str]:
    """Recursively find all .json files in the directory.

    Args:
        directory: Path to directory to search

    Returns:
        List of file paths for all .json files found
    """
    directory_path = Path(directory)
    if not directory_path.exists():
        return []

    json_files = list(directory_path.rglob("*.json"))
    return [str(f) for f in json_files]
