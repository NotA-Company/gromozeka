"""
Golden Data Provider for OpenWeatherMapClient testing.

This module provides a GoldenDataProvider class that can patch the OpenWeatherMapClient
to use golden data instead of making real API calls during testing.
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from lib.openweathermap.client import OpenWeatherMapClient
from tests.golden_data.openweathermap.types import GoldenDataFile

logger = logging.getLogger(__name__)


class GoldenDataProvider:
    """
    Provider for OpenWeatherMap golden data testing.
    
    Loads all golden data files from the raw/ directory and provides
    a method to patch the OpenWeatherMapClient to return golden data
    instead of making real API calls.
    """

    def __init__(self):
        """
        Initialize the GoldenDataProvider.
        
        Loads all golden data files from the raw/ directory into memory
        for quick lookup during testing.
        """
        self.scriptDir = Path(__file__).parent
        self.rawDir = self.scriptDir / "raw"
        self.inputsDir = self.scriptDir / "inputs"
        self.missingDataLog = self.inputsDir / "missing_data.log"
        
        # Ensure inputs directory exists
        self.inputsDir.mkdir(parents=True, exist_ok=True)
        
        # Load all golden data files
        self.goldenData: Dict[str, str] = {}
        self._loadGoldenData()
        
    def _loadGoldenData(self) -> None:
        """
        Load all golden data files from the raw/ directory.
        
        Parses each file as GoldenDataFile and creates lookup keys
        from URL and parameters in the request section.
        """
        if not self.rawDir.exists():
            logger.warning(f"Raw directory not found: {self.rawDir}")
            return
            
        for filePath in self.rawDir.glob("*.json"):
            try:
                with open(filePath, "r", encoding="utf-8") as f:
                    data: GoldenDataFile = json.load(f)
                
                # Process each entry in the file
                for entry in data:
                    requestInfo = entry["request"]
                    url = requestInfo["url"]
                    params = requestInfo["params"]
                    
                    # Create lookup key from URL and parameters
                    key = self._createLookupKey(url, params)
                    
                    # Store the raw response
                    self.goldenData[key] = entry["response"]["raw"]
                    
            except Exception as e:
                logger.error(f"Error loading golden data from {filePath}: {e}")
                
    def _createLookupKey(self, url: str, params: Dict[str, str]) -> str:
        """
        Create a unique key for lookup based on URL and parameters.
        
        Args:
            url: API endpoint URL
            params: Dictionary of query parameters (as strings)
            
        Returns:
            String key for lookup
        """
        # Remove apikey from parameters as it's redacted in golden data
        cleanParams = {k: v for k, v in params.items() if k != "appid"}
        
        # Sort parameters for consistent ordering
        sortedParams = sorted(cleanParams.items())
        
        # Create key parts
        keyParts = [url]
        for key, value in sortedParams:
            keyParts.append(f"{key}={value}")
            
        return "|".join(keyParts)
        
    def _findGoldenData(self, url: str, params: Dict[str, str]) -> str:
        """
        Find and return raw response for the given URL and parameters.
        
        Args:
            url: API endpoint URL
            params: Dictionary of query parameters
            
        Returns:
            Raw response string from golden data
            
        Raises:
            KeyError: If golden data is not found for the request
        """
        key = self._createLookupKey(url, params)
        
        if key in self.goldenData:
            return self.goldenData[key]
        else:
            # Log missing data and raise exception
            self._logMissingData(url, params)
            raise KeyError(f"Golden data not found for URL {url} with params {params}")
            
    def _logMissingData(self, url: str, params: Dict[str, str]) -> None:
        """
        Log missing golden data to a file.
        
        Args:
            url: API endpoint URL
            params: Dictionary of query parameters
        """
        timestamp = datetime.now().isoformat()
        logEntry = {
            "timestamp": timestamp,
            "url": url,
            "params": params
        }
        
        # Append to missing data log
        try:
            with open(self.missingDataLog, "a", encoding="utf-8") as f:
                f.write(json.dumps(logEntry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Error writing to missing data log: {e}")
            
        logger.warning(f"Missing golden data logged: {url} with params {params}")
        
    @asynccontextmanager
    async def patchClient(self, client: OpenWeatherMapClient):
        """
        Async context manager that patches the client's _makeRequest method.
        
        Args:
            client: OpenWeatherMapClient instance to patch
            
        Yields:
            The patched client
            
        Example:
            provider = GoldenDataProvider()
            client = OpenWeatherMapClient(apiKey="test", cache=cache)
            
            async with provider.patchClient(client):
                # Client will now return golden data instead of making real API calls
                result = await client.getWeatherByCity("Minsk", "BY")
        """
        # Store original method
        originalMakeRequest = client._makeRequest
        
        # Create patched method
        async def patchedMakeRequest(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """
            Patched version of _makeRequest that returns golden data.
            
            Args:
                url: API endpoint URL
                params: Query parameters
                
            Returns:
                Parsed JSON response from golden data
            """
            try:
                # Convert all parameters to strings as they appear in golden data
                stringParams = {k: str(v) for k, v in params.items()}
                
                # Find golden data
                rawData = self._findGoldenData(url, stringParams)
                
                # Parse and return JSON data
                return json.loads(rawData)
                
            except KeyError:
                # Golden data not found - return None to match client behavior
                return None
            except json.JSONDecodeError as e:
                # Invalid JSON in golden data
                raise Exception(f"Invalid JSON in golden data for URL {url}: {e}")
                
        # Apply patch
        client._makeRequest = patchedMakeRequest
        
        try:
            # Yield control to the caller
            yield client
        finally:
            # Restore original method
            client._makeRequest = originalMakeRequest