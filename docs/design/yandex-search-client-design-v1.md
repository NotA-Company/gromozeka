# Yandex Search API Client Design Document v1

## Overview

This document explains the architecture decisions, design patterns, and implementation details of the Yandex Search API client library. The client provides a high-level async interface to the Yandex Search API v2 with XML response format, featuring caching, rate limiting, and comprehensive error handling.

## Architecture Decisions

### 1. Async-First Design

**Decision**: Implemented as a fully async library using `asyncio` and `httpx`.

**Rationale**:
- Modern Python applications increasingly use async patterns
- Non-blocking I/O is essential for high-performance applications
- Integrates seamlessly with the existing async codebase (Telegram bot)
- Allows concurrent search requests without thread management complexity

**Implementation**:
```python
async def search(self, ...) -> Optional[SearchResponse]:
    # Creates new session for each request
    async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
        response = await session.post(...)
```

### 2. Session-per-Request Pattern

**Decision**: Create a new HTTP session for each request instead of reusing a persistent session.

**Rationale**:
- Avoids connection pooling issues in concurrent environments
- Eliminates potential session state conflicts
- httpx handles connection pooling internally at the transport level
- Simplifies thread safety considerations

**Trade-offs**:
- Slightly higher overhead for connection establishment
- Mitigated by httpx's connection reuse at the transport level
- Acceptable for search API usage patterns (not high-frequency requests)

### 3. TypedDict Models

**Decision**: Use `TypedDict` for data models instead of dataclasses or Pydantic models.

**Rationale**:
- Runtime compatibility with regular dictionaries
- Zero serialization/deserialization overhead
- Consistent with existing project patterns (OpenWeatherMap client)
- Sufficient type checking support with static type checkers
- Simple and lightweight for API response structures

**Example**:
```python
class SearchResponse(TypedDict):
    requestId: str
    found: int
    foundHuman: str
    page: int
    groups: List[SearchGroup]
    error: Optional[Dict]
```

### 4. Abstract Cache Interface

**Decision**: Define an abstract cache interface to support multiple storage backends.

**Rationale**:
- Flexibility to use different cache implementations
- Testability with mock caches
- Future-proof for database or Redis caches
- Follows dependency inversion principle
- Consistent with project's caching patterns

**Implementation**:
```python
class SearchCacheInterface(ABC):
    @abstractmethod
    async def getSearch(self, key: str, ttl: Optional[int] = None) -> Optional[SearchResponse]:
        pass
    
    @abstractmethod
    async def setSearch(self, key: str, data: SearchResponse) -> bool:
        pass
```

## Caching Strategy

### 1. Cache Key Generation

**Design**: MD5 hash of normalized request parameters.

**Implementation Details**:
```python
def _generate_cache_key(self, request: SearchRequest) -> str:
    cache_data = {
        "query": request["query"],
        "sortSpec": request["sortSpec"],
        "groupSpec": request["groupSpec"],
        "metadata": {k: v for k, v in request["metadata"].items() if k != "folderId"}
    }
    sorted_json = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(sorted_json.encode('utf-8')).hexdigest()
```

**Rationale**:
- MD5 provides sufficient uniqueness for cache keys
- JSON serialization ensures consistent key generation
- Excluding folderId allows cache sharing across clients
- Sorting parameters ensures order-independent keys

### 2. TTL Management

**Design**: Per-entry timestamps with configurable default TTL.

**Implementation**:
```python
# Store as (data, timestamp) tuple
self.search_cache: Dict[str, Tuple[SearchResponse, float]] = {}

# Check expiration
def _is_expired(self, timestamp: float, ttl: Optional[int] = None) -> bool:
    effective_ttl = ttl if ttl is not None else self.default_ttl
    return time.time() - timestamp > effective_ttl
```

**Features**:
- Flexible TTL per request
- Automatic cleanup of expired entries
- Configurable default TTL
- Support for immediate expiration (TTL=0) and no expiration (TTL<0)

### 3. Size Management

**Design**: LRU-like eviction based on timestamps.

**Algorithm**:
1. Check if cache exceeds max size
2. Sort entries by timestamp (oldest first)
3. Remove excess entries
4. Maintain thread safety with locks

**Rationale**:
- Simple implementation with good performance
- Timestamp-based eviction approximates LRU behavior
- Suitable for search result caching patterns

## Rate Limiting Implementation

### 1. Sliding Window Algorithm

**Design**: Track request timestamps in a sliding time window.

**Implementation**:
```python
async def _apply_rate_limit(self) -> None:
    async with self._rateLimitLock:
        current_time = time.time()
        
        # Remove old requests outside window
        self._requestTimes = [
            req_time for req_time in self._requestTimes
            if current_time - req_time < self.rateLimitWindow
        ]
        
        # Check if limit exceeded
        if len(self._requestTimes) >= self.rateLimitRequests:
            oldest_request = min(self._requestTimes)
            wait_time = self.rateLimitWindow - (current_time - oldest_request)
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        # Add current request
        self._requestTimes.append(current_time)
```

**Advantages**:
- Accurate rate limiting without fixed buckets
- Smooth request distribution
- Configurable windows and limits
- Thread-safe with async locks

### 2. Statistics and Monitoring

**Design**: Provide real-time rate limiting statistics.

**Metrics**:
- Requests in current window
- Maximum allowed requests
- Window duration
- Reset time estimation

## Error Handling Approach

### 1. Hierarchical Error Handling

**Design**: Handle errors at different levels with appropriate responses.

**Levels**:
1. **Network Level**: Timeouts, connection errors
2. **HTTP Level**: Status codes (4xx, 5xx)
3. **API Level**: Error responses in XML
4. **Parsing Level**: XML/JSON parsing errors

### 2. Graceful Degradation

**Strategy**: Return None for errors, log appropriately, use cache when possible.

```python
try:
    # API request
    response = await session.post(...)
    if response.status_code == 200:
        return parseSearchResponse(responseData)
    elif response.status_code == 429:
        logger.error("Rate limit exceeded")
        return None
except httpx.TimeoutException:
    logger.error("Request timeout")
    return None
```

### 3. Error Information Preservation

**Design**: Include error information in SearchResponse when available.

```python
if errorElement is not None:
    return {
        'requestId': '',
        'found': 0,
        'foundHuman': '',
        'page': 0,
        'groups': [],
        'error': {
            'code': errorCode,
            'message': errorMessage,
            'details': errorDetails
        }
    }
```

## Performance Optimizations

### 1. Connection Management

**Optimization**: Leverage httpx's connection pooling at transport level.

**Benefits**:
- Automatic connection reuse
- HTTP/2 support
- Keep-alive connections
- No manual connection management needed

### 2. XML Parsing

**Optimization**: Use standard library `xml.etree.ElementTree` with efficient parsing.

```python
def parseSearchResponse(base64Xml: str) -> SearchResponse:
    # Decode Base64
    xmlBytes = base64.b64decode(base64Xml)
    xmlString = xmlBytes.decode('utf-8')
    
    # Parse XML
    root = ET.fromstring(xmlString)
    
    # Extract data efficiently
    groups = []
    for groupElement in root.findall('.//group'):
        group = _parseGroup(groupElement)
        if group:
            groups.append(group)
```

### 3. Cache Efficiency

**Optimizations**:
- Lazy cleanup (only when needed)
- Batch operations where possible
- Minimal locking duration
- Efficient key generation

## Security Considerations

### 1. Credential Management

**Practices**:
- Never log credentials
- Support both IAM tokens and API keys
- Clear separation of authentication methods
- No credential persistence

### 2. Input Validation

**Approach**:
- Rely on API validation for query parameters
- Handle special characters in queries
- Safe XML parsing against injection
- Base64 validation for responses

### 3. Rate Limiting

**Protection**:
- Client-side rate limiting to prevent abuse
- Configurable limits per use case
- Monitoring capabilities
- Graceful handling of limit exceeded

## Testing Strategy

### 1. Unit Testing

**Coverage**:
- Client methods (19 tests)
- Cache implementation (11 tests)
- XML parsing
- Error scenarios
- Rate limiting

### 2. Mock Strategy

**Approach**:
- Mock HTTP responses for client tests
- Mock time for rate limiting tests
- Use fixtures for consistent test data
- Test both success and failure scenarios

### 3. Integration Testing

**Scenarios**:
- End-to-end search flows
- Cache integration
- Rate limiting behavior
- Error propagation

## Future Enhancements

### 1. Database Cache

**Planned**: Implement `DatabaseSearchCache` using project's database wrapper.

**Benefits**:
- Persistent caching across restarts
- Shared cache across processes
- Larger cache capacity
- Integration with existing database

### 2. Batch Operations

**Consideration**: Support for multiple queries in a single request.

**Challenges**:
- API limitations
- Response complexity
- Cache key management
- Error handling granularity

### 3. Response Filtering

**Enhancement**: Advanced result filtering options.

**Features**:
- Domain filtering
- Date range filtering
- Content type filtering
- Custom ranking

### 4. Metrics Collection

**Addition**: Request/response metrics and monitoring.

**Metrics**:
- Request latency
- Cache hit/miss ratios
- Error rates
- API usage patterns

## Conclusion

The Yandex Search API client design prioritizes:
- **Performance**: Async operations, efficient caching, connection pooling
- **Reliability**: Comprehensive error handling, rate limiting, graceful degradation
- **Flexibility**: Pluggable cache, configurable parameters, multiple auth methods
- **Maintainability**: Clear architecture, comprehensive tests, good documentation

The design follows established project patterns while introducing optimizations specific to search API requirements. The modular architecture allows for future enhancements while maintaining backward compatibility.

## Version History

- **v1.0** (2025-10-31): Initial design and implementation
  - Core client functionality
  - In-memory caching
  - Rate limiting
  - Comprehensive error handling
  - Full test coverage