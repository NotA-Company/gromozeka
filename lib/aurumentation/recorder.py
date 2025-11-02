"""Recording coordinator for golden data testing.

This module implements the recording coordinator that manages the
recording process using custom httpx transports.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from .masker import SecretMasker
from .transports import RecordingTransport
from .types import GoldenDataFileFormat, GoldenDataScenarioDict, HttpCallDict, MetadataDict


class GoldenDataRecorder:
    """Coordinates the recording of HTTP traffic for golden data testing.

    This class manages the recording process by patching httpx globally
    with RecordingTransport, collecting recorded recordings, and creating
    complete scenarios with metadata.
    """

    def __init__(self, secrets: Optional[List[str]] = None):
        """Initialize the recorder.

        Args:
            secrets: List of secrets to mask in recorded data
        """
        self.secrets = secrets or []
        self.transport: Optional[RecordingTransport] = None
        self.originalTransportClass = None
        self.recordings: List[HttpCallDict] = []

    async def __aenter__(self) -> "GoldenDataRecorder":
        """Enter the async context manager and patch httpx globally.

        Returns:
            The recorder instance
        """
        # Create recording transport
        print("HttpxRecorder: Initializing RecordingTransport")
        defaultTransport = httpx.AsyncHTTPTransport()
        self.transport = RecordingTransport(wrapped=defaultTransport)

        # Store reference to self for use in the class
        recorder_self = self

        # Patch httpx.AsyncClient to use our transport
        self.originalClientClass = httpx.AsyncClient

        class PatchedAsyncClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                print("Patching httpx.AsyncClient...")
                # Force our transport to be used
                kwargs["transport"] = recorder_self.transport
                super().__init__(*args, **kwargs)

        httpx.AsyncClient = PatchedAsyncClient
        print("HttpxRecorder: Patched httpx.AsyncClient")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager and restore httpx.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        # Restore original httpx.AsyncClient
        if self.originalClientClass:
            httpx.AsyncClient = self.originalClientClass
            print("HttpxRecorder: Restored original httpx.AsyncClient")

    def getRecordedRecordings(self) -> List[HttpCallDict]:
        """Get all recorded recordings, with secrets masked.

        Returns:
            List of recorded HttpCallDict objects with secrets masked
        """
        if not self.transport:
            return []

        # Get recordings from transport
        rawCalls = self.transport.recordings
        print(f"Returning {len(rawCalls)} recordings")

        # Mask secrets in recordings
        masker = SecretMasker(secrets=self.secrets)
        maskedCalls = [masker.maskHttpCall(call) for call in rawCalls]

        return maskedCalls

    def clearRecordedCalls(self) -> None:
        """Clear the recording buffer."""
        if self.transport:
            self.transport.recordings.clear()
        self.recordings.clear()

    def createScenario(
        self,
        *,
        description: str,
        scenarioName: Optional[str],
        module: str,
        className: str,
        method: str,
        kwargs: Dict,
        initKwargs: Optional[Dict] = None,
        recordings: Optional[List[HttpCallDict]] = None,
    ) -> GoldenDataScenarioDict:
        """Create a complete scenario with metadata.

        Args:
            description: Description of the test scenario
            module: Module path of the class being tested
            class_name: Name of the class being tested
            method: Name of the method being tested
            kwargs: Keyword arguments for the method
            init_kwargs: Keyword arguments for class initialization
            recordings: List of HttpCallDict objects. If None, uses recorded recordings.

        Returns:
            A complete GoldenDataScenarioDict with metadata
        """
        if recordings is None:
            recordings = self.getRecordedRecordings()

        if scenarioName is None:
            scenarioName = description

        nowStr = datetime.now(timezone.utc).isoformat()
        # Create metadata
        metadata: MetadataDict = {
            "name": scenarioName,
            "description": description,
            "module": module,
            "class": className,
            "method": method,
            "init_kwargs": initKwargs or {},
            "kwargs": kwargs,
            "createdAt": nowStr,
        }

        # Create a scenario-like object with the metadata
        return {
            "name": scenarioName,
            "description": description,
            "functionName": f"{className}.{method}",
            "metadata": metadata,  # Store the full metadata
            "recordings": recordings,
            "createdAt": nowStr,
        }

    def saveGoldenData(self, filepath: str, metadata: MetadataDict) -> None:
        """Save recorded recordings as golden data with metadata.

        Args:
            filepath: Path to save the golden data file
            metadata: Metadata about the scenario
        """
        # Get recorded recordings
        recordings = self.getRecordedRecordings()

        # Create the golden data structure
        golden_data: GoldenDataFileFormat = {
            "metadata": metadata,
            "recordings": recordings,
        }

        # Save to file
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(golden_data, f, indent=2, default=str, ensure_ascii=False)

    def _substituteEnvVars(self, value: str) -> str:
        """Substitute environment variables in a string.

        Args:
            value: String that may contain ${VAR_NAME} patterns

        Returns:
            String with environment variables substituted
        """
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            var_name = value[2:-1]
            return os.getenv(var_name, value)
        return value
