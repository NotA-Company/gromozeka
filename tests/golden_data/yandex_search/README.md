# Yandex Search Golden Data Testing System

This directory implements a golden data testing system for the Yandex Search API client, following the same pattern as the OpenWeatherMap implementation.

## Directory Structure

- `types.py` - TypedDict definitions for golden data structure
- `__init__.py` - Exports the GoldenDataProvider class and types
- `provider.py` - GoldenDataProvider class implementation
- `collect.py` - Script to collect real API responses for testing
- `inputs/` - Input data for collection
  - `search_queries.json` - Search queries to collect data for
  - `README.md` - Documentation for input data
- `golden/` - Collected golden data files (populated by collector)

## Usage

### Collecting Golden Data

To collect golden data from the real Yandex Search API:

1. Ensure you have a `.env` file with `YANDEX_SEARCH_API_KEY` and `YANDEX_SEARCH_FOLDER_ID` set
2. Run the collection script:
   ```bash
   ./venv/bin/python3 tests/golden_data/yandex_search/collect.py
   ```

### Using in Tests

To use the golden data in tests:

```python
import pytest
from lib.yandex_search.client import YandexSearchClient
from lib.yandex_search.dict_cache import DictSearchCache
from tests.golden_data.yandex_search import GoldenDataProvider

@pytest.mark.asyncio
async def testSearch():
    provider = GoldenDataProvider()
    cache = DictSearchCache()
    
    client = YandexSearchClient(
        apiKey="test_key",
        folderId="test_folder",
        cache=cache
    )
    
    async with provider.patchClient(client) as patched_client:
        result = await patched_client.search("python programming")
        assert result is not None
        assert "groups" in result
        # Add more assertions based on expected golden data
```

## Golden Data Format

Each golden data file contains a list of entries with:

- `call` - Information about the API call made
- `request` - Information about the HTTP request
- `response` - Information about the HTTP response, including the raw XML

The data is collected by patching the client's `_makeRequest` method to capture the raw responses.