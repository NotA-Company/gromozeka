#!/usr/bin/env python3
"""
Golden Data Collection Script for Yandex Search API

This script collects real API responses from Yandex Search and saves them
as golden data for testing. It uses the actual YandexSearchClient methods
but patches HTTP calls to capture raw responses.

Usage:
    ./venv/bin/python3 tests/golden_data/yandex_search/collect.py

Requirements:
    - .env file with YANDEX_SEARCH_API_KEY and YANDEX_SEARCH_FOLDER_ID
    - inputs/search_queries.json with test search queries
"""
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib import utils  # noqa: E402
from lib.yandex_search.client import YandexSearchClient  # noqa: E402
from lib.yandex_search.dict_cache import DictSearchCache  # noqa: E402
from lib.yandex_search.models import SearchRequest, SearchResponse  # noqa: E402
from tests.golden_data.yandex_search.types import YandexSearchGoldenDataEntry  # noqa: E402

REDACTED_API_KEY = "REDACTED_API_KEY"
REDACTED_FOLDER_ID = "REDACTED_FOLDER_ID"


class GoldenDataCollector:
    """Collects golden data from Yandex Search API using actual client methods."""

    def __init__(self, apiKey: str, folderId: str, outputDir: Path):
        """
        Initialize collector.

        Args:
            apiKey: Yandex Search API key
            folderId: Yandex Cloud folder ID
            outputDir: Directory to save golden data
        """
        self.apiKey = apiKey
        self.folderId = folderId
        self.outputDir = outputDir
        self.outputDir.mkdir(parents=True, exist_ok=True)

    async def collectSearch(self, queryText: str, description: str = "") -> None:
        """
        Collect search data for a query using actual client method.

        Args:
            queryText: Search query text
            description: Optional description for the file name
        """
        print(f"Collecting search results for query: '{queryText}'...")

        client = YandexSearchClient(
            apiKey=self.apiKey,
            folderId=self.folderId,
            cache=DictSearchCache(),
            useCache=False,  # Disable caching for collection
        )

        requests: List[YandexSearchGoldenDataEntry] = []

        # Patch the _makeRequest method to capture raw responses
        original_make_request = client._makeRequest

        async def patched_make_request(request: SearchRequest) -> Optional[SearchResponse]:
            """Patched version of _makeRequest that captures raw responses."""
            import base64

            import httpx

            # Build URL and parameters for logging
            url = YandexSearchClient.API_ENDPOINT

            # Extract query parameters from request
            params = request.copy()
            params["folderId"] = REDACTED_FOLDER_ID

            data: YandexSearchGoldenDataEntry = {
                "call": {
                    "method": "search",
                    "params": {
                        "queryText": queryText,
                    },
                    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                "request": {
                    "json": params,  # pyright: ignore[reportAssignmentType]
                },
                "response": {
                    "raw": "",
                    "status_code": 0,
                },
            }

            # Make the actual request
            async with httpx.AsyncClient(timeout=client.requestTimeout) as session:
                response = await session.post(
                    url,
                    headers={"Content-Type": "application/json", "Authorization": f"Api-Key {self.apiKey}"},
                    json=request,
                )
                raw_response = response.text
                data["response"]["raw"] = raw_response
                data["response"]["status_code"] = response.status_code
                requests.append(data)

                # Return parsed response for normal client operation
                if response.status_code == 200:
                    # Parse JSON response
                    responseData = response.json()

                    # Extract Base64-encoded XML
                    if "rawData" not in responseData:
                        print("Error: No 'rawData' field in response")
                        return None

                    base64Xml = responseData["rawData"]

                    # Parse XML response (this is what the real client does)
                    from lib.yandex_search.xml_parser import parseSearchResponse

                    result = parseSearchResponse(base64Xml)
                    return result  # pyright: ignore[reportReturnType]
                else:
                    print(f"Error: API request failed with status {response.status_code}")
                    print(f"Response text: {response.text}")
                    return None

        # Apply the patch
        client._makeRequest = patched_make_request  # pyright: ignore[reportAttributeAccessIssue]

        try:
            # Call the client method - this will use our patched _makeRequest
            _ = await client.search(queryText)

            # Sanitize query for filename
            filenameQuery = self._sanitize_filename(queryText)

            filename = f"search.{filenameQuery}.json"
            if description:
                filenameQueryDesc = self._sanitize_filename(description)
                filename = f"search.{filenameQueryDesc}.{filenameQuery}.json"
            filepath = self.outputDir / filename
            with open(filepath, "w") as f:
                f.write(utils.jsonDumps(requests, indent=2))

        except Exception as e:
            print(f" Error collecting search results for '{queryText}': {e}")
        finally:
            # Restore original method
            client._makeRequest = original_make_request

    def _sanitize_filename(self, text: str) -> str:
        """
        Sanitize text for use in filename.

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text suitable for filename
        """
        # Replace special characters with underscores
        sanitized = "".join(c if c.isalnum() or c in " _-" else "_" for c in text)
        # Remove multiple consecutive underscores
        while "__" in sanitized:
            sanitized = sanitized.replace("__", "_")
        # Strip leading/trailing underscores and whitespace
        sanitized = sanitized.strip("_ ")
        # Limit length
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
        return sanitized or "unnamed"


async def main():
    """Main collection workflow."""
    # Load environment variables (try .env.test first for testing)
    utils.load_dotenv()
    apiKey = os.getenv("YANDEX_SEARCH_API_KEY")
    folderId = os.getenv("YANDEX_SEARCH_FOLDER_ID")

    if not apiKey:
        print("Error: YANDEX_SEARCH_API_KEY not found in .env or .env.test file")
        return

    if not folderId:
        print("Error: YANDEX_SEARCH_FOLDER_ID not found in .env or .env.test file")
        return

    # Setup paths
    scriptDir = Path(__file__).parent
    inputsDir = scriptDir / "inputs"
    outputsDir = scriptDir / "golden"  # Save to golden directory

    # Load input data
    searchQueriesFile = inputsDir / "search_queries.json"
    if not searchQueriesFile.exists():
        print(f"Error: {searchQueriesFile} not found")
        return

    with open(searchQueriesFile, "r", encoding="utf-8") as f:
        searchQueries = json.load(f)

    # Initialize collector
    collector = GoldenDataCollector(apiKey=apiKey, folderId=folderId, outputDir=outputsDir)

    # Collect data for each search query
    print(f"\n  Collecting golden data for {len(searchQueries)} search queries...\n")

    for queryData in searchQueries:
        queryText = queryData["query"]
        description = queryData.get("description", "")

        try:
            # Collect search results
            await collector.collectSearch(queryText, description)

            print()  # Empty line between queries

        except Exception as e:
            print(f"Error collecting data for query '{queryText}': {e}\n")
            continue

    print("\nGolden data collection complete!")
    print(f" Data saved to: {outputsDir}")


if __name__ == "__main__":
    asyncio.run(main())
