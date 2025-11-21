# Yandex Search API Client Implementation Plan

## Overview

This document outlines the implementation plan for creating a Yandex Search API client in the `lib/yandex_search` directory. The client will use the Text Search API with XML output format and follow the latest API v2 specification.

## Requirements Analysis

Based on the Yandex Search API documentation, the client needs to:

1. **API Version**: Use Yandex Search API v2 (REST)
2. **Output Format**: XML format (default, with option for HTML)
3. **Authentication**: Support both IAM token and API key authentication
4. **Search Types**: Support multiple search domains (RU, TR, COM, KK, BE, UZ)
5. **Response Format**: Handle Base64-encoded XML responses
6. **Caching**: Implement caching similar to OpenWeatherMap client
7. **Error Handling**: Comprehensive error handling for API responses

## Architecture Design

The client will follow the established project patterns:

```
lib/yandex_search/
├── __init__.py              # Main exports
├── client.py                # Main YandexSearchClient class
├── models.py                # TypedDict models for requests/responses
├── cache_interface.py       # Abstract cache interface
├── xml_parser.py            # XML response parsing utilities
├── dict_cache.py            # In-memory cache implementation
├── examples.py              # Usage examples
├── README.md                # Documentation
├── test_client.py           # Client tests
└── test_xml_parser.py       # XML parser tests
```

## Implementation Details

### 1. Data Models (`models.py`)

Define TypedDict classes for:

- **SearchQuery**: Query parameters (searchType, queryText, familyMode, page, fixTypoMode)
- **SortSpec**: Sorting parameters (sortMode, sortOrder)
- **GroupSpec**: Grouping parameters (groupMode, groupsOnPage, docsInGroup)
- **SearchMetadata**: Search flags and metadata
- **SearchRequest**: Complete request structure
- **SearchResult**: Individual search result
- **SearchGroup**: Group of search results
- **SearchResponse**: Parsed XML response structure
- **ErrorResponse**: Error response structure

### 2. Cache Interface (`cache_interface.py`)

Abstract interface following the project pattern:

```python
class SearchCacheInterface(ABC):
    @abstractmethod
    async def getSearch(self, key: str, ttl: Optional[int] = None) -> Optional[SearchResponse]:
        pass
    
    @abstractmethod
    async def setSearch(self, key: str, data: SearchResponse) -> bool:
        pass
```

### 3. XML Parser (`xml_parser.py`)

Utilities for parsing Yandex Search XML responses:

- Parse Base64-encoded XML responses
- Extract search results, metadata, and error information
- Handle highlighted words (`<hlword>` tags)
- Parse document metadata (url, title, passages, etc.)

### 4. Main Client (`client.py`)

The `YandexSearchClient` class will provide:

- **Authentication**: Support for IAM token and API key
- **Search Methods**:
  - `search()` - Basic search with full parameters
  - `searchSimple()` - Simplified search with common defaults
- **Caching**: Optional caching with configurable TTL
- **Error Handling**: Comprehensive error handling and logging
- **Rate Limiting**: Basic rate limiting to prevent API abuse

### 5. Cache Implementation (`dict_cache.py`)

In-memory cache implementation similar to OpenWeatherMap client:

- Thread-safe caching with TTL support
- Configurable cache size limits
- Cache key generation based on query parameters

## API Integration Details

### Authentication

The client will support two authentication methods:

1. **IAM Token**: `Authorization: Bearer <IAM_token>`
2. **API Key**: `Authorization: Api-Key <API_key>`

### Request Structure

```python
# Example request structure
request = {
    "query": {
        "searchType": "SEARCH_TYPE_RU",
        "queryText": "example search query",
        "familyMode": "FAMILY_MODE_MODERATE",
        "page": "0",
        "fixTypoMode": "FIX_TYPO_MODE_ON"
    },
    "sortSpec": {
        "sortMode": "SORT_MODE_BY_RELEVANCE",
        "sortOrder": "SORT_ORDER_DESC"
    },
    "groupSpec": {
        "groupMode": "GROUP_MODE_DEEP",
        "groupsOnPage": "10",
        "docsInGroup": "2"
    },
    "maxPassages": "2",
    "region": "225",  # Russia
    "l10n": "LOCALIZATION_RU",
    "folderId": "folder_id",
    "responseFormat": "FORMAT_XML"
}
```

### Response Processing

1. Receive Base64-encoded XML response
2. Decode and parse XML
3. Extract search results and metadata
4. Convert to structured Python objects
5. Cache results if caching is enabled

## Testing Strategy

### Unit Tests

1. **Client Tests** (`test_client.py`):
   - Test authentication methods
   - Test request formation
   - Test error handling
   - Test caching functionality

2. **XML Parser Tests** (`test_xml_parser.py`):
   - Test XML parsing with various response formats
   - Test error response parsing
   - Test special character handling

### Test Data

Create mock XML responses for:
- Successful search results
- Error responses
- Empty results
- Malformed XML

## Configuration

The client will accept configuration for:

- API credentials (IAM token or API key)
- Folder ID
- Default search parameters
- Cache settings (TTL, size limits)
- Request timeout
- Rate limiting settings

## Usage Examples

```python
# Basic usage
from lib.yandex_search import YandexSearchClient

client = YandexSearchClient(
    api_key="your_api_key",
    folder_id="your_folder_id"
)

results = await client.searchSimple("python programming")

# Advanced usage with caching
from lib.yandex_search.dict_cache import DictSearchCache

cache = DictSearchCache(max_size=1000, default_ttl=3600)
client = YandexSearchClient(
    api_key="your_api_key",
    folder_id="your_folder_id",
    cache=cache
)

results = await client.search(
    query_text="machine learning",
    search_type="SEARCH_TYPE_RU",
    region="225",
    max_passages=3
)
```

## Implementation Phases

### Phase 1: Core Implementation
1. Create data models
2. Implement basic client without caching
3. Implement XML parser
4. Add basic tests

### Phase 2: Caching and Advanced Features
1. Implement cache interface and in-memory cache
2. Add caching to client
3. Implement rate limiting
4. Add comprehensive tests

### Phase 3: Documentation and Integration
1. Write comprehensive documentation
2. Create usage examples
3. Update project files
4. Performance testing and optimization

## Dependencies

The client will require:

- `httpx` - For HTTP requests (already in project)
- `xml.etree.ElementTree` - For XML parsing (standard library)
- `base64` - For response decoding (standard library)
- `typing` - For type hints (standard library)
- `asyncio` - For async operations (standard library)

## Security Considerations

1. **Credential Management**: Never log or expose API credentials
2. **Input Validation**: Validate all input parameters
3. **Error Handling**: Don't expose sensitive information in error messages
4. **Rate Limiting**: Implement client-side rate limiting

## Performance Considerations

1. **Connection Pooling**: Use httpx's connection pooling
2. **Caching**: Implement intelligent caching with appropriate TTL
3. **Timeouts**: Configure appropriate request timeouts
4. **Memory Usage**: Monitor cache size and implement eviction policies

## Future Enhancements

1. **Async Search**: Support for asynchronous search operations
2. **Batch Operations**: Support for multiple queries in one request
3. **Result Filtering**: Advanced result filtering options
4. **Custom Parsers**: Pluggable response parsers
5. **Metrics**: Request/response metrics and monitoring