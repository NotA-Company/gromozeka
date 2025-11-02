"""
Golden Data Provider for YandexSearchClient testing.

This module provides a GoldenDataProvider class that can patch the YandexSearchClient
to use golden data instead of making real API calls during testing.
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from lib import utils
from lib.yandex_search.client import YandexSearchClient
from lib.yandex_search.models import SearchRequest, SearchResponse
from lib.yandex_search.xml_parser import parseSearchResponse
from tests.golden_data.yandex_search.types import YandexSearchGoldenDataFile

logger = logging.getLogger(__name__)


class GoldenDataProvider:
    """
    Provider for Yandex Search golden data testing.

    Loads all golden data files from the golden/ directory and provides
    a method to patch the YandexSearchClient to return golden data
    instead of making real API calls.
    """

    def __init__(self):
        """
        Initialize the GoldenDataProvider.

        Loads all golden data files from the golden/ directory into memory
        for quick lookup during testing.
        """
        self.scriptDir = Path(__file__).parent
        self.goldenDir = self.scriptDir / "golden"
        self.inputsDir = self.scriptDir / "inputs"
        self.missingDataLog = self.inputsDir / "missing_data.log"

        # Ensure inputs directory exists
        self.inputsDir.mkdir(parents=True, exist_ok=True)

        # Load all golden data files
        self.goldenData: Dict[str, str] = {}
        self._loadGoldenData()

    def _loadGoldenData(self) -> None:
        """
        Load all golden data files from the golden/ directory.

        Parses each file as YandexSearchGoldenDataFile and creates lookup keys
        from URL and parameters in the request section.
        """
        if not self.goldenDir.exists():
            logger.warning(f"Golden directory not found: {self.goldenDir}")
            return

        for filePath in self.goldenDir.glob("*.json"):
            try:
                with open(filePath, "r", encoding="utf-8") as f:
                    data: YandexSearchGoldenDataFile = json.load(f)

                # Process each entry in the file
                for entry in data:
                    requestInfo = entry["request"]
                    params = requestInfo["json"]

                    # Create lookup key from URL and parameters
                    key = self._createLookupKey(params)  # pyright: ignore[reportArgumentType]

                    # Store the raw response (XML)
                    # The raw data is a JSON string with a "rawData" field containing base64-encoded XML
                    rawResponse = entry["response"]["raw"]
                    rawResponseData = json.loads(rawResponse)
                    self.goldenData[key] = rawResponseData["rawData"]

            except Exception as e:
                logger.error(f"Error loading golden data from {filePath}: {e}")

    def _createLookupKey(self, params: SearchRequest) -> str:
        """
        Create a unique key for lookup based on URL and parameters.

        Args:
            params: Dictionary of query parameters (as strings)

        Returns:
            String key for lookup
        """
        # Remove folderId from parameters as they're redacted in golden data
        cleanParams = {k: v for k, v in params.items() if k not in ["folderId"]}

        return utils.jsonDumps(cleanParams)

    def _findGoldenData(self, params: SearchRequest) -> str:
        """
        Find and return raw response for the given URL and parameters.

        Args:
            url: API endpoint URL
            params: Dictionary of query parameters

        Returns:
            Raw response string from golden data (XML)

        Raises:
            KeyError: If golden data is not found for the request
        """
        key = self._createLookupKey(params)

        if key in self.goldenData:
            return self.goldenData[key]
        else:
            # Log missing data and raise exception
            self._logMissingData(params)
            raise KeyError(f"Golden data not found for params {params}")

    def _logMissingData(self, params: SearchRequest) -> None:
        """
        Log missing golden data to a file.

        Args:
            url: API endpoint URL
            params: Dictionary of query parameters
        """
        timestamp = datetime.now().isoformat()
        logEntry = {
            "timestamp": timestamp,
            "params": params,
        }

        # Append to missing data log
        try:
            with open(self.missingDataLog, "a", encoding="utf-8") as f:
                f.write(utils.jsonDumps(logEntry) + "\n")
        except Exception as e:
            logger.error(f"Error writing to missing data log: {e}")

        logger.warning(f"Missing golden data logged: params {params}")

    @asynccontextmanager
    async def patchClient(self, client: YandexSearchClient):
        """
        Async context manager that patches the client's _makeRequest method.

        Args:
            client: YandexSearchClient instance to patch

        Yields:
            The patched client

        Example:
            provider = GoldenDataProvider()
            client = YandexSearchClient(apiKey="test", folderId="test")

            async with provider.patchClient(client):
                # Client will now return golden data instead of making real API calls
                result = await client.search("python programming")
        """
        # Store original method
        originalMakeRequest = client._makeRequest

        # Create patched method
        async def patchedMakeRequest(request: SearchRequest) -> Optional[SearchResponse]:
            """
            Patched version of _makeRequest that returns golden data.

            Args:
                request: Search request dictionary

            Returns:
                Parsed XML response from golden data as dictionary
            """
            try:
                # Find golden data (XML)
                rawXml = self._findGoldenData(request)

                # Parse XML and return as dictionary
                # This mimics the behavior of parseSearchResponse function
                return parseSearchResponse(rawXml)  # type: ignore

            except KeyError:
                # Golden data not found - return None to match client behavior
                return None
            except Exception as e:
                # Error in parsing or other issues
                raise Exception(f"Error processing golden data for request: {e}")

        # Apply patch
        client._makeRequest = patchedMakeRequest  # type: ignore

        try:
            # Yield control to the caller
            yield client
        finally:
            # Restore original method
            client._makeRequest = originalMakeRequest
