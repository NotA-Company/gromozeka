# Yandex Search API Async Client Library

A comprehensive async client library for the Yandex Search API v2 with XML response format, designed for the Gromozeka Telegram bot project.

## Features

- 🔍 **Multiple Search Domains**: Support for RU, TR, COM, KK, BE, UZ search domains
- 🔐 **Flexible Authentication**: Support for both IAM token and API key authentication
- 💾 **Intelligent Caching**: Configurable caching with TTL support
- 🚀 **Rate Limiting**: Built-in rate limiting to prevent API abuse
- 🌐 **Async/Await**: Full async support for high performance
- 🛡️ **Error Handling**: Robust error handling and logging
- 🧪 **Well Tested**: Comprehensive test suite with 30+ tests
- 📝 **Typed Models**: Full type hints with TypedDict models

## Quick Start

### Basic Usage

```python
from lib.yandex_search import YandexSearchClient

# Initialize with IAM token
client = YandexSearchClient(
    iam_token="your_iam_token",
    folder_id="your_folder_id"
)

# Simple search
results = await client.searchSimple("python programming")

if results:
    print(f"Found {results['found']} results")
    for group in results['groups']:
        for doc in group['group']:
            print(f"Title: {doc['title']}")
            print(f"URL: {doc['url']}")
```

### Advanced Usage with Caching

```python
from lib.yandex_search import YandexSearchClient, DictSearchCache

# Initialize cache
cache = DictSearchCache(
    default_ttl=3600,  # 1 hour
    max_size=1000
)

# Create client with cache
client = YandexSearchClient(
    iam_token="your_iam_token",
    folder_id="your_folder_id",
    cache=cache,
    rate_limit_requests=20,
    rate_limit_window=60
)

# Advanced search
results = await client.search(
    query_text="machine learning",
    search_type="SEARCH_TYPE_RU",
    region="225",
    max_passages=3,
    groups_on_page=5,
    docs_in_group=2
)
```

## Configuration

### Authentication

The client supports two authentication methods:

#### IAM Token (Recommended)
```python
client = YandexSearchClient(
    iam_token="t1.9euel9q...",  # Get from Yandex Cloud IAM
    folder_id="b1g8v1h2..."     # Your folder ID
)
```

#### API Key
```python
client = YandexSearchClient(
    api_key="AQVN1...",         # Create in Yandex Cloud console
    folder_id="b1g8v1h2..."     # Your folder ID
)
```

### Cache Configuration

```python
from lib.yandex_search import DictSearchCache

# In-memory cache
cache = DictSearchCache(
    default_ttl=3600,  # 1 hour TTL
    max_size=1000      # Maximum 1000 entries
)

# Use with client
client = YandexSearchClient(
    iam_token="your_token",
    folder_id="your_folder",
    cache=cache,
    cache_ttl=1800,      # Override default TTL
    bypass_cache=False   # Enable caching
)
```

### Rate Limiting

```python
client = YandexSearchClient(
    iam_token="your_token",
    folder_id="your_folder",
    rate_limit_requests=10,  # 10 requests per window
    rate_limit_window=60     # 60 second window
)

# Check rate limit status
stats = client.get_rate_limit_stats()
print(f"Used {stats['requests_in_window']}/{stats['max_requests']} requests")
```

## API Reference

### YandexSearchClient

Main client class for interacting with the Yandex Search API.

#### Constructor

```python
YandexSearchClient(
    iam_token: Optional[str] = None,
    api_key: Optional[str] = None,
    folder_id: str,
    request_timeout: int = 30,
    cache: Optional[SearchCacheInterface] = None,
    cache_ttl: Optional[int] = 3600,
    bypass_cache: bool = False,
    rate_limit_requests: int = 10,
    rate_limit_window: int = 60
)
```

#### Methods

##### `search(queryText, **kwargs)`

Perform search with full parameter control.

**Parameters:**
- `queryText` (str): Search query text
- `searchType` (str): Search domain (default: "SEARCH_TYPE_RU")
- `familyMode` (str, optional): Family filter mode
- `page` (int, optional): Page number (0-based)
- `fixTypoMode` (str, optional): Typo correction mode
- `sortMode` (str, optional): Sort mode
- `sortOrder` (str, optional): Sort order
- `groupMode` (str, optional): Grouping mode
- `groupsOnPage` (int, optional): Groups per page
- `docsInGroup` (int, optional): Documents per group
- `maxPassages` (int, optional): Maximum passages
- `region` (str, optional): Region code
- `l10n` (str, optional): Localization
- `bypassCache` (bool, optional): Bypass cache for this request

**Returns:** `SearchResponse` or `None`

**Example:**
```python
results = await client.search(
    query_text="machine learning",
    search_type="SEARCH_TYPE_RU",
    region="225",
    max_passages=3
)
```

##### `searchSimple(queryText, **kwargs)`

Perform simplified search with sensible defaults.

**Parameters:**
- `queryText` (str): Search query text
- `searchType` (str): Search domain (default: "SEARCH_TYPE_RU")
- `maxPassages` (int): Maximum passages (default: 2)
- `groupsOnPage` (int): Groups per page (default: 10)
- `docsInGroup` (int): Documents per group (default: 2)
- `bypassCache` (bool, optional): Bypass cache for this request

**Returns:** `SearchResponse` or `None`

##### `get_rate_limit_stats()`

Get current rate limiting statistics.

**Returns:** Dictionary with rate limiting information

**Example:**
```python
stats = client.get_rate_limit_stats()
print(f"Requests: {stats['requests_in_window']}/{stats['max_requests']}")
print(f"Window resets at: {stats['reset_time']}")
```

### Data Models

#### SearchQuery
```python
{
    "searchType": str,              # SEARCH_TYPE_RU, SEARCH_TYPE_TR, etc.
    "queryText": str,               # Search query text
    "familyMode": Optional[str],    # FAMILY_MODE_MODERATE, etc.
    "page": Optional[str],          # Page number (0-based)
    "fixTypoMode": Optional[str]    # FIX_TYPO_MODE_ON, FIX_TYPO_MODE_OFF
}
```

#### SearchResponse
```python
{
    "requestId": str,               # Unique request identifier
    "found": int,                   # Total results found
    "foundHuman": str,              # Human-readable count
    "page": int,                    # Current page number
    "groups": List[SearchGroup],    # Result groups
    "error": Optional[Dict]         # Error information
}
```

#### SearchResult
```python
{
    "url": str,                     # Document URL
    "domain": str,                  # Domain name
    "title": str,                   # Document title
    "passages": List[str],          # Text passages with highlights
    "modtime": Optional[str],       # Modification time
    "size": Optional[str],          # Document size
    "charset": Optional[str],       # Character encoding
    "mimetypes": Optional[List[str]], # MIME types
    "hlwords": Optional[List[str]]   # Highlighted words
}
```

## Caching

The library provides a flexible caching system to reduce API calls and improve performance.

### Cache Interface

```python
class SearchCacheInterface(ABC):
    async def getSearch(self, key: str, ttl: Optional[int] = None) -> Optional[SearchResponse]
    async def setSearch(self, key: str, data: SearchResponse) -> bool
```

### DictSearchCache

In-memory cache implementation with thread safety:

```python
cache = DictSearchCache(
    default_ttl=3600,  # 1 hour
    max_size=1000      # 1000 entries max
)

# Cache statistics
stats = cache.get_stats()
print(f"Cache usage: {stats['search_entries']}/{stats['max_size']}")

# Generate cache key
key = cache.generate_key_from_params(
    query="python programming",
    region="225"
)
```

### Cache Behavior

- **Cache Keys**: MD5 hash of search parameters
- **TTL**: Configurable time-to-live for entries
- **Size Limits**: Automatic eviction of oldest entries
- **Thread Safety**: Safe for concurrent access
- **Bypass Option**: Per-request cache bypass

## Error Handling

The client handles various error scenarios gracefully:

### API Errors
- **400 Bad Request**: Invalid parameters → logs error, returns None
- **401 Unauthorized**: Invalid credentials → logs error, returns None
- **403 Forbidden**: Insufficient permissions → logs error, returns None
- **429 Too Many Requests**: Rate limit → logs error, waits if needed
- **500+ Server Errors**: API issues → logs error, returns None

### Network Errors
- **Timeout**: Logs error, returns cached data if available
- **Connection Error**: Logs error, returns cached data if available
- **DNS Error**: Logs error, returns None

### Cache Errors
- **Storage Error**: Logs error, continues without cache
- **Key Generation Error**: Logs error, bypasses cache

## Search Domains

The client supports multiple Yandex search domains:

| Domain | Code | Description |
|--------|------|-------------|
| Russian | SEARCH_TYPE_RU | yandex.ru |
| Turkish | SEARCH_TYPE_TR | yandex.com.tr |
| International | SEARCH_TYPE_COM | yandex.com |
| Kazakh | SEARCH_TYPE_KK | yandex.kz |
| Belarusian | SEARCH_TYPE_BE | yandex.by |
| Uzbek | SEARCH_TYPE_UZ | yandex.uz |

## Bot Integration

### Telegram Bot Example

```python
from lib.yandex_search import YandexSearchClient, DictSearchCache

# Initialize cache and client
cache = DictSearchCache(default_ttl=1800)
client = YandexSearchClient(
    iam_token="your_token",
    folder_id="your_folder",
    cache=cache
)

async def search_command(update, context):
    """Handle /search command"""
    query = " ".join(context.args) if context.args else "python"
    
    results = await client.searchSimple(query)
    
    if results:
        message = f"🔍 **{results['foundHuman']} результатов**\n\n"
        
        for group in results['groups'][:3]:  # Show first 3 groups
            for doc in group['group']:
                message += f"📄 [{doc['title']}]({doc['url']})\n"
                if doc['passages']:
                    message += f"_{doc['passages'][0][:100]}..._\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Ничего не найдено, dood!")
```

## Testing

Run the test suite:

```bash
# Run all tests
./venv/bin/python3 -m pytest lib/yandex_search/ -v

# Run specific test file
./venv/bin/python3 -m pytest lib/yandex_search/test_client.py -v

# Run with coverage
./venv/bin/python3 -m pytest lib/yandex_search/ --cov=lib.yandex_search
```

### Test Coverage

The test suite includes:
- ✅ Client tests (19 tests)
- ✅ Cache tests (11 tests)
- ✅ XML parser tests
- ✅ Error handling tests
- ✅ Rate limiting tests
- ✅ Integration tests

## Examples

See `examples.py` for comprehensive usage examples:

```bash
./venv/bin/python3 lib/yandex_search/examples.py
```

Examples include:
- Basic and advanced searches
- Authentication methods
- Caching demonstrations
- Rate limiting
- Error handling
- Different search domains
- Cache key generation

## Performance Considerations

### Caching Strategy
- **Default TTL**: 1 hour for general searches
- **Cache Keys**: MD5 hash of normalized parameters
- **Size Limits**: Configurable with LRU-like eviction
- **Memory Usage**: Monitor with `get_stats()`

### Rate Limiting
- **Default**: 10 requests per 60 seconds
- **Algorithm**: Sliding window with async lock
- **Monitoring**: Real-time statistics available
- **Customization**: Configurable per client

### Connection Management
- **Session-per-request**: New HTTP session for each request
- **Timeouts**: Configurable request timeout (default: 30s)
- **Concurrency**: Safe for concurrent async operations

## Getting API Credentials

### 1. Get Yandex Cloud Account
1. Go to [Yandex Cloud](https://cloud.yandex.com/)
2. Create an account or sign in
3. Create a new folder for your project

### 2. Create Service Account
1. Go to Service Accounts in Yandex Cloud console
2. Create a new service account
3. Assign appropriate roles (`ai.searcher` or similar)

### 3. Get Credentials

#### IAM Token (Recommended)
```bash
# Create IAM token
yc iam create-token --service-account-name <account-name>
```

#### API Key
1. Go to API Keys in Yandex Cloud console
2. Create new API key
3. Save the key securely

### 4. Find Folder ID
```bash
# Get folder ID
yc resource-manager folder list
```

## Dependencies

The library uses these dependencies (already in the project):
- `httpx` - Async HTTP client
- `xml.etree.ElementTree` - XML parsing (standard library)
- `base64` - Base64 decoding (standard library)
- `hashlib` - MD5 hashing (standard library)
- `typing` - Type hints (standard library)
- `asyncio` - Async operations (standard library)
- `threading` - Thread safety (standard library)

## Architecture

The library follows the project's established patterns:

```
lib/yandex_search/
├── __init__.py              # Module exports
├── client.py                # Main client class
├── models.py                # Data models (TypedDicts)
├── xml_parser.py            # XML response parsing
├── cache_interface.py       # Abstract cache interface
├── dict_cache.py            # In-memory cache implementation
├── examples.py              # Usage examples
├── test_client.py           # Client tests
├── test_dict_cache.py       # Cache tests
└── README.md                # This documentation
```

### Design Patterns Used
- **Abstract Factory**: Cache interface allows different implementations
- **Template Method**: Client provides common API request handling
- **Strategy**: Different cache strategies (memory, database, etc.)
- **Facade**: Simple interface hiding complex API interactions
- **Decorator**: Rate limiting applied to requests

## Security Best Practices

### Credential Management
- Never hardcode credentials in source code
- Use environment variables or secure configuration
- Rotate IAM tokens regularly
- Use API keys only for development/testing

### Input Validation
- All query parameters are validated by the API
- Client handles special characters in queries
- XML parsing is protected against injection

### Rate Limiting
- Always configure appropriate rate limits
- Monitor API usage to avoid quotas
- Use caching to reduce API calls

### Logging
- Never log credentials or sensitive data
- Use appropriate log levels
- Monitor error logs for issues

## Contributing

When contributing to this library:

1. Follow the project's camelCase naming convention
2. Add comprehensive tests for new features
3. Update documentation and examples
4. Use the project's logging patterns
5. Follow the existing error handling patterns
6. Ensure type hints are complete and accurate

## License

This library is part of the Gromozeka project and follows the same license terms.