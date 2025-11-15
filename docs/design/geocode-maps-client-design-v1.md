# Geocode Maps API Client Design Document

**Version:** 1.0  
**Date:** 2025-11-14  
**Status:** Design Phase  
**Author:** SourceCraft Code Assistant

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Architecture Analysis](#architecture-analysis)
4. [Data Models](#data-models)
5. [Client Architecture](#client-architecture)
6. [Cache Integration](#cache-integration)
7. [Rate Limiter Integration](#rate-limiter-integration)
8. [Error Handling](#error-handling)
9. [Implementation Plan](#implementation-plan)
10. [Testing Strategy](#testing-strategy)
11. [References](#references)

## Overview

This document describes the design for a Python async client library for the Geocode Maps API (geocode.maps.co). The client will provide type-safe, cached, and rate-limited access to geocoding services including forward geocoding (address to coordinates), reverse geocoding (coordinates to address), and OSM object lookup, dood!

### Goals

- **Type Safety**: Use TypedDict for all data models with comprehensive type hints, dood
- **Performance**: Implement efficient caching with configurable TTL, dood
- **Reliability**: Integrate rate limiting to prevent API quota exhaustion, dood
- **Consistency**: Follow established patterns from [`lib.openweathermap`](lib/openweathermap/client.py) and [`lib.yandex_search`](lib/yandex_search/client.py), dood
- **Maintainability**: Clear separation of concerns with well-documented code, dood

### Non-Goals

- Support for formats other than `jsonv2` (can be added later if needed), dood
- Batch processing utilities (can be built on top of the client), dood
- Synchronous API (async-only design), dood

## Requirements

Based on [`docs/design/geocode-maps-client-design-v0.md`](docs/design/geocode-maps-client-design-v0.md):

1. **HTTP Client**: Use `httpx` for async HTTP requests, dood
2. **Caching**: Use [`lib.cache`](lib/cache/interface.py) interface for result caching, dood
3. **Rate Limiting**: Use [`lib.rate_limiter`](lib/rate_limiter/manager.py) with default queue `geocode-maps`, dood
4. **Authentication**: Use `Authorization: Bearer YOUR_SECRET_API_KEY` HTTP header, dood
5. **Output Format**: Always use `jsonv2` format for responses, dood
6. **Request Method**: Implement `_makeRequest()` as single point for all HTTP requests, dood
7. **Language Support**: Support global `accept-language` setting per client instance, dood

### API Endpoints

The client must support three endpoints from [`docs/other/geocode-maps/Geocode-Maps-API.md`](docs/other/geocode-maps/Geocode-Maps-API.md):

1. **`/search`** - Forward geocoding (address → coordinates), dood
2. **`/reverse`** - Reverse geocoding (coordinates → address), dood
3. **`/lookup`** - OSM object lookup by ID, dood

## Architecture Analysis

### Comparison with Existing Implementations

#### OpenWeatherMap Client Pattern

From [`lib/openweathermap/client.py`](lib/openweathermap/client.py:1-381):

**Strengths:**
- Clean separation between geocoding and weather data caching, dood
- Simple cache key generation (string-based), dood
- Clear method naming (`getCoordinates()`, `getWeather()`, `getWeatherByCity()`), dood
- Comprehensive error handling in `_makeRequest()`, dood

**Patterns to Adopt:**
- Separate cache instances for different data types, dood
- Round coordinates for cache keys (4 decimal places ≈ 11m precision), dood
- Use camelCase for method names (project convention), dood
- Create new `httpx.AsyncClient` per request for thread safety, dood

#### Yandex Search Client Pattern

From [`lib/yandex_search/client.py`](lib/yandex_search/client.py:1-278):

**Strengths:**
- Complex request object as cache key (using custom key generator), dood
- Comprehensive TypedDict models with enums, dood
- Detailed docstrings with examples, dood
- Bearer token authentication pattern, dood

**Patterns to Adopt:**
- Use TypedDict for request/response structures, dood
- Implement detailed logging at debug level, dood
- Support both API key and alternative auth methods, dood
- Cache entire request objects when appropriate, dood

### Key Design Decisions

1. **Cache Strategy**: Use separate cache instances for each endpoint type (search, reverse, lookup), dood
2. **Cache Keys**: Use string-based keys for simplicity (following OpenWeatherMap pattern), dood
3. **Authentication**: Support only Bearer token (as per API docs), dood
4. **Language Handling**: Store `acceptLanguage` as instance variable, apply to all requests, dood
5. **Error Handling**: Return `Optional[T]` for all methods, log errors, never raise exceptions, dood

## Data Models

All models will be defined in [`lib/geocode_maps/models.py`](lib/geocode_maps/models.py) using TypedDict for runtime compatibility and type safety, dood!

### Response Models

Based on example responses in [`docs/other/geocode-maps/`](docs/other/geocode-maps/):

#### Address Components

```python
class Address(TypedDict, total=False):
    """Structured address components from geocoding response, dood!
    
    All fields are optional as different locations have different address structures.
    """
    road: str                    # Street name
    neighbourhood: str           # Neighbourhood/district
    suburb: str                  # Suburb name
    city: str                    # City name
    county: str                  # County/district name
    state: str                   # State/region name
    postcode: str               # Postal code
    country: str                # Country name
    country_code: str           # ISO country code (e.g., "ru")
    region: str                 # Region name
    amenity: str                # Amenity name (if applicable)
    # ISO 3166-2 level 4 code
    ISO3166_2_lvl4: str         # ISO 3166-2 subdivision code
```

#### Name Details

```python
class NameDetails(TypedDict, total=False):
    """Name translations in different languages, dood!"""
    name: str                   # Default name
    int_name: str              # International name
    # Language-specific names (examples)
    name_en: str               # English name
    name_ru: str               # Russian name
    name_de: str               # German name
    name_fr: str               # French name
    name_ja: str               # Japanese name
    name_zh: str               # Chinese name
    # ... additional language codes as needed
```

#### Extra Tags

```python
class ExtraTags(TypedDict, total=False):
    """Additional OSM tags and metadata, dood!"""
    website: str               # Official website URL
    wikidata: str             # Wikidata ID
    wikipedia: str            # Wikipedia article reference
    population: str           # Population count
    start_date: str           # Establishment date
    linked_place: str         # Linked place type
    official_status: str      # Official administrative status
    area: str                 # Area indicator
    surface: str              # Surface type
    # ... additional OSM tags as needed
```

#### Search Result

```python
class SearchResult(TypedDict):
    """Single result from /search endpoint, dood!"""
    place_id: int                      # Unique place identifier
    licence: str                       # Data licence information
    osm_type: str                      # OSM object type (node/way/relation)
    osm_id: int                        # OSM object ID
    lat: str                           # Latitude (string in API response)
    lon: str                           # Longitude (string in API response)
    category: str                      # Place category
    type: str                          # Place type
    place_rank: int                    # Place importance rank
    importance: float                  # Importance score (0-1)
    addresstype: str                   # Address type
    name: str                          # Place name
    display_name: str                  # Full display name
    address: Address                   # Structured address components
    boundingbox: List[str]            # Bounding box [min_lat, max_lat, min_lon, max_lon]
    extratags: NotRequired[ExtraTags] # Optional extra OSM tags
    namedetails: NotRequired[NameDetails]  # Optional name translations
    geotext: NotRequired[str]         # Optional geometry as WKT polygon
```

#### Reverse Result

```python
class ReverseResult(TypedDict):
    """Result from /reverse endpoint, dood!"""
    place_id: int                      # Unique place identifier
    licence: str                       # Data licence information
    osm_type: str                      # OSM object type
    osm_id: int                        # OSM object ID
    lat: str                           # Latitude (string in API response)
    lon: str                           # Longitude (string in API response)
    category: str                      # Place category
    type: str                          # Place type
    place_rank: int                    # Place importance rank
    importance: float                  # Importance score
    addresstype: str                   # Address type
    name: str                          # Place name
    display_name: str                  # Full display name
    address: Address                   # Structured address components
    boundingbox: List[str]            # Bounding box
    extratags: NotRequired[ExtraTags] # Optional extra OSM tags
    namedetails: NotRequired[NameDetails]  # Optional name translations
```

#### Lookup Result

```python
class LookupResult(TypedDict):
    """Result from /lookup endpoint, dood!"""
    place_id: int                      # Unique place identifier
    licence: str                       # Data licence information
    osm_type: str                      # OSM object type
    osm_id: int                        # OSM object ID
    lat: str                           # Latitude (string in API response)
    lon: str                           # Longitude (string in API response)
    category: str                      # Place category
    type: str                          # Place type
    place_rank: int                    # Place importance rank
    importance: float                  # Importance score
    addresstype: str                   # Address type
    name: str                          # Place name
    display_name: str                  # Full display name
    address: Address                   # Structured address components
    boundingbox: List[str]            # Bounding box
    extratags: NotRequired[ExtraTags] # Optional extra OSM tags
    namedetails: NotRequired[NameDetails]  # Optional name translations
    geotext: NotRequired[str]         # Optional geometry as WKT polygon
```

### Type Aliases

```python
# Response types for each endpoint
SearchResponse = List[SearchResult]    # /search returns array
ReverseResponse = ReverseResult        # /reverse returns single object
LookupResponse = List[LookupResult]    # /lookup returns array
```

### Helper Models

```python
class Coordinates(TypedDict):
    """Latitude/longitude pair, dood!"""
    lat: float
    lon: float
```

## Client Architecture

### Class Structure

```python
class GeocodeMapsClient:
    """Async client for Geocode Maps API with caching and rate limiting, dood!
    
    Provides type-safe access to geocoding services with automatic caching
    and rate limiting. Creates new HTTP session for each request to support
    proper concurrent operations.
    
    Example:
        >>> from lib.geocode_maps import GeocodeMapsClient
        >>> from lib.cache import DictCache
        >>> 
        >>> client = GeocodeMapsClient(
        ...     apiKey="your_api_key",
        ...     searchCache=DictCache(),
        ...     reverseCache=DictCache(),
        ...     lookupCache=DictCache(),
        ...     searchTTL=2592000,      # 30 days
        ...     reverseTTL=2592000,     # 30 days
        ...     lookupTTL=2592000,      # 30 days
        ...     acceptLanguage="en"
        ... )
        >>> 
        >>> # Forward geocoding
        >>> results = await client.search("Angarsk, Russia")
        >>> 
        >>> # Reverse geocoding
        >>> location = await client.reverse(52.5443, 103.8882)
        >>> 
        >>> # OSM lookup
        >>> places = await client.lookup(["R2623018"])
    """
```

### Constructor Parameters

```python
def __init__(
    self,
    apiKey: str,
    searchCache: Optional[CacheInterface[str, SearchResponse]] = None,
    reverseCache: Optional[CacheInterface[str, ReverseResponse]] = None,
    lookupCache: Optional[CacheInterface[str, LookupResponse]] = None,
    searchTTL: Optional[int] = 2592000,      # 30 days (geocoding rarely changes)
    reverseTTL: Optional[int] = 2592000,     # 30 days
    lookupTTL: Optional[int] = 2592000,      # 30 days
    requestTimeout: int = 10,
    acceptLanguage: str = "en",
    rateLimiterQueue: str = "geocode-maps",
):
    """Initialize Geocode Maps client, dood!
    
    Args:
        apiKey: Geocode Maps API key (required)
        searchCache: Cache for search results (default: NullCache)
        reverseCache: Cache for reverse geocoding results (default: NullCache)
        lookupCache: Cache for lookup results (default: NullCache)
        searchTTL: Cache TTL for search results in seconds (default: 30 days)
        reverseTTL: Cache TTL for reverse results in seconds (default: 30 days)
        lookupTTL: Cache TTL for lookup results in seconds (default: 30 days)
        requestTimeout: HTTP request timeout in seconds (default: 10)
        acceptLanguage: Language for results (e.g., "en", "ru", "fr")
        rateLimiterQueue: Rate limiter queue name (default: "geocode-maps")
    """
```

### Public Methods

#### search()

```python
async def search(
    self,
    query: str,
    *,
    limit: int = 10,
    countrycodes: Optional[str] = None,
    viewbox: Optional[str] = None,
    bounded: bool = False,
    addressdetails: bool = True,
    extratags: bool = True,
    namedetails: bool = True,
    dedupe: bool = True,
) -> Optional[SearchResponse]:
    """Forward geocoding: convert address to coordinates, dood!
    
    Searches for locations matching the query string and returns
    geographic coordinates and structured address information.
    
    Args:
        query: Free-form search query (e.g., "Angarsk, Russia")
        limit: Maximum number of results (0-40, default: 10)
        countrycodes: Comma-separated country codes to restrict search (e.g., "ru,us")
        viewbox: Bounding box to bias search (format: "min_lon,min_lat,max_lon,max_lat")
        bounded: Restrict results to viewbox (default: False)
        addressdetails: Include structured address (default: True)
        extratags: Include extra OSM tags (default: True)
        namedetails: Include name translations (default: True)
        dedupe: Remove duplicate results (default: True)
    
    Returns:
        List of search results or None if error occurs
        
    Cache key format: "search:{query}:{limit}:{countrycodes}:{viewbox}:{bounded}"
    
    Example:
        >>> results = await client.search("Angarsk, Russia", limit=5)
        >>> if results:
        ...     first = results[0]
        ...     print(f"Found: {first['display_name']}")
        ...     print(f"Coordinates: {first['lat']}, {first['lon']}")
    """
```

#### reverse()

```python
async def reverse(
    self,
    lat: float,
    lon: float,
    *,
    zoom: Optional[int] = None,
    addressdetails: bool = True,
    extratags: bool = True,
    namedetails: bool = True,
) -> Optional[ReverseResponse]:
    """Reverse geocoding: convert coordinates to address, dood!
    
    Finds the nearest OSM object to the given coordinates and returns
    its address and metadata.
    
    Args:
        lat: Latitude (-90 to 90)
        lon: Longitude (-180 to 180)
        zoom: Detail level (3-18, higher = more detailed)
        addressdetails: Include structured address (default: True)
        extratags: Include extra OSM tags (default: True)
        namedetails: Include name translations (default: True)
    
    Returns:
        Reverse geocoding result or None if error occurs
        
    Cache key format: "reverse:{lat_rounded}:{lon_rounded}:{zoom}"
    Coordinates are rounded to 4 decimal places (~11m precision)
    
    Example:
        >>> location = await client.reverse(52.5443, 103.8882)
        >>> if location:
        ...     print(f"Address: {location['display_name']}")
        ...     print(f"City: {location['address'].get('city', 'N/A')}")
    """
```

#### lookup()

```python
async def lookup(
    self,
    osmIds: List[str],
    *,
    addressdetails: bool = True,
    extratags: bool = True,
    namedetails: bool = True,
    polygonGeojson: bool = False,
    polygonKml: bool = False,
    polygonSvg: bool = False,
    polygonText: bool = False,
) -> Optional[LookupResponse]:
    """Lookup OSM objects by ID, dood!
    
    Retrieves details for one or more OSM objects using their IDs.
    IDs must include type prefix: N (node), W (way), or R (relation).
    
    Args:
        osmIds: List of OSM IDs with type prefix (e.g., ["R2623018", "N107775"])
        addressdetails: Include structured address (default: True)
        extratags: Include extra OSM tags (default: True)
        namedetails: Include name translations (default: True)
        polygonGeojson: Include GeoJSON polygon (default: False)
        polygonKml: Include KML polygon (default: False)
        polygonSvg: Include SVG polygon (default: False)
        polygonText: Include WKT polygon (default: False)
    
    Returns:
        List of lookup results or None if error occurs
        
    Cache key format: "lookup:{sorted_osm_ids}:{polygon_flags}"
    
    Example:
        >>> places = await client.lookup(["R2623018"])
        >>> if places:
        ...     place = places[0]
        ...     print(f"Place: {place['name']}")
        ...     print(f"Type: {place['type']}")
    """
```

### Private Methods

#### _makeRequest()

```python
async def _makeRequest(
    self,
    endpoint: str,
    params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Make HTTP request to Geocode Maps API, dood!
    
    Single point for all HTTP requests with error handling, rate limiting,
    and authentication. Creates new session per request for thread safety.
    
    Args:
        endpoint: API endpoint path (e.g., "search", "reverse", "lookup")
        params: Query parameters (api_key and format added automatically)
    
    Returns:
        Parsed JSON response or None on error
        
    Error Handling:
        - 401: Invalid API key (logs error, returns None)
        - 404: Location not found (logs warning, returns None)
        - 429: Rate limit exceeded (logs error, returns None)
        - 5xx: Server error (logs error, returns None)
        - Timeout: Request timeout (logs error, returns None)
        - Network: Connection error (logs error, returns None)
    """
```

#### _buildCacheKey()

```python
def _buildCacheKey(self, prefix: str, *parts: Any) -> str:
    """Build cache key from components, dood!
    
    Creates consistent cache keys by joining prefix and parts with colons.
    Handles None values and converts all parts to strings.
    
    Args:
        prefix: Key prefix (e.g., "search", "reverse", "lookup")
        *parts: Variable number of key components
    
    Returns:
        Cache key string (e.g., "search:angarsk:10:ru")
        
    Example:
        >>> key = self._buildCacheKey("search", "Angarsk", 10, "ru")
        >>> # Returns: "search:angarsk:10:ru"
    """
```

## Cache Integration

### Cache Strategy

Following the pattern from [`lib/openweathermap/client.py`](lib/openweathermap/client.py:50-86), we'll use separate cache instances for each endpoint type, dood!

**Rationale:**
- Different data types have different characteristics, dood
- Allows independent TTL configuration per endpoint, dood
- Simplifies cache key generation, dood
- Enables selective cache clearing, dood

### Cache Key Design

#### Search Cache Keys

Format: `search:{normalized_query}:{limit}:{countrycodes}:{viewbox}:{bounded}`

Example: `search:angarsk russia:10:ru::false`

**Normalization:**
- Convert query to lowercase, dood
- Trim whitespace, dood
- Keep original spacing for accuracy, dood

#### Reverse Cache Keys

Format: `reverse:{lat_rounded}:{lon_rounded}:{zoom}`

Example: `reverse:52.5443:103.8882:18`

**Coordinate Rounding:**
- Round to 4 decimal places (~11 meter precision), dood
- Balances cache efficiency with location accuracy, dood
- Same precision as OpenWeatherMap client, dood

#### Lookup Cache Keys

Format: `lookup:{sorted_osm_ids}:{polygon_flags}`

Example: `lookup:R2623018,W205445534:0000`

**ID Sorting:**
- Sort OSM IDs alphabetically for consistent keys, dood
- Polygon flags as 4-bit string (geojson, kml, svg, text), dood

### Cache TTL Recommendations

Based on data volatility analysis:

- **Search Results**: 30 days (2,592,000 seconds)
  - Place names and coordinates rarely change, dood
  - Long TTL reduces API calls significantly, dood

- **Reverse Results**: 30 days (2,592,000 seconds)
  - Address assignments are stable, dood
  - Same rationale as search, dood

- **Lookup Results**: 30 days (2,592,000 seconds)
  - OSM object metadata is relatively stable, dood
  - Geometry data changes infrequently, dood

### Cache Implementation Example

```python
from lib.cache import DictCache, StringKeyGenerator

# Create separate caches for each endpoint
searchCache = DictCache[str, SearchResponse](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=2592000,  # 30 days
    maxSize=10000
)

reverseCache = DictCache[str, ReverseResponse](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=2592000,  # 30 days
    maxSize=10000
)

lookupCache = DictCache[str, LookupResponse](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=2592000,  # 30 days
    maxSize=5000
)

client = GeocodeMapsClient(
    apiKey="your_api_key",
    searchCache=searchCache,
    reverseCache=reverseCache,
    lookupCache=lookupCache
)
```

## Rate Limiter Integration

### Configuration

Following the pattern from [`lib/openweathermap/client.py`](lib/openweathermap/client.py:59-86) and [`lib/yandex_search/client.py`](lib/yandex_search/client.py:73-111), dood!

```python
from lib.rate_limiter import RateLimiterManager, SlidingWindowRateLimiter, QueueConfig

# Initialize rate limiter at application startup
manager = RateLimiterManager.getInstance()

# Create rate limiter for Geocode Maps API
# Free tier: typically 1 request/second or 60 requests/minute
geocodeLimiter = SlidingWindowRateLimiter(
    QueueConfig(
        maxRequests=60,      # Max requests
        windowSeconds=60     # Time window
    )
)
await geocodeLimiter.initialize()

# Register with manager
manager.registerRateLimiter("geocode-maps-limiter", geocodeLimiter)
manager.bindQueue("geocode-maps", "geocode-maps-limiter")
```

### Usage in Client

```python
async def _makeRequest(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Make HTTP request with rate limiting, dood!"""
    try:
        logger.debug(f"Making request to {endpoint} with params: {params}")
        
        # Apply rate limiting before request
        await self._rateLimiter.applyLimit(self.rateLimiterQueue)
        
        # Prepare request...
        # (rest of implementation)
```

### Rate Limit Recommendations

Based on typical geocoding API limits:

- **Free Tier**: 1 request/second (60 requests/minute), dood
- **Paid Tier**: Higher limits based on plan, dood

**Configuration Strategy:**
- Start conservative (1 req/sec), dood
- Monitor API responses for rate limit headers, dood
- Adjust based on actual API plan, dood
- Use separate queue name for easy reconfiguration, dood

## Error Handling

### Error Handling Strategy

Following the established pattern of returning `Optional[T]` and logging errors, dood!

### HTTP Status Codes

```python
async def _makeRequest(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handle all HTTP status codes, dood!"""
    try:
        async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
            response = await session.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"API request successful: {response.status_code}")
                return data
                
            elif response.status_code == 401:
                logger.error("Invalid API key")
                return None
                
            elif response.status_code == 404:
                logger.warning("Location not found")
                return None
                
            elif response.status_code == 429:
                logger.error("Rate limit exceeded")
                return None
                
            elif response.status_code >= 500:
                logger.error(f"Server error: {response.status_code}")
                return None
                
            else:
                logger.error(f"API request failed: {response.status_code}")
                logger.error(f"Response text: {response.text}")
                return None
                
    except httpx.TimeoutException:
        logger.error("Request timeout")
        return None
        
    except httpx.RequestError as e:
        logger.error(f"Network error: {e}")
        return None
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        return None
        
    except Exception as e:
        logger.error(f"Unexpected error during API request: {e}")
        return None
```

### Cache Error Handling

```python
# Check cache with error handling
try:
    cachedData = await self.searchCache.get(cacheKey, self.searchTTL)
    if cachedData:
        logger.debug(f"Cache hit for search: {cacheKey}")
        return cachedData
except Exception as e:
    logger.warning(f"Cache error for search {cacheKey}: {e}")
    # Continue to API request

# Store in cache with error handling
try:
    await self.searchCache.set(cacheKey, result)
    logger.debug(f"Cached search result: {cacheKey}")
except Exception as e:
    logger.warning(f"Failed to cache search result {cacheKey}: {e}")
    # Return result anyway
```

## Implementation Plan

### Phase 1: Core Structure (Priority: High)

1. **Create module structure**, dood:
   ```
   lib/geocode_maps/
   ├── __init__.py
   ├── client.py
   ├── models.py
   └── README.md
   ```

2. **Implement data models** in [`models.py`](lib/geocode_maps/models.py), dood:
   - Define all TypedDict classes, dood
   - Add comprehensive docstrings, dood
   - Include usage examples, dood

3. **Implement client skeleton** in [`client.py`](lib/geocode_maps/client.py), dood:
   - Class definition with `__init__()`, dood
   - Method signatures with docstrings, dood
   - Import statements, dood

### Phase 2: Core Functionality (Priority: High)

4. **Implement `_makeRequest()` method**, dood:
   - HTTP request handling, dood
   - Authentication header, dood
   - Error handling, dood
   - Rate limiting integration, dood

5. **Implement `_buildCacheKey()` helper**, dood:
   - Key generation logic, dood
   - Normalization, dood
   - Consistent formatting, dood

6. **Implement `search()` method**, dood:
   - Parameter validation, dood
   - Cache key generation, dood
   - Cache check, dood
   - API request, dood
   - Cache storage, dood

### Phase 3: Additional Endpoints (Priority: High)

7. **Implement `reverse()` method**, dood:
   - Coordinate rounding, dood
   - Cache integration, dood
   - API request, dood

8. **Implement `lookup()` method**, dood:
   - OSM ID validation, dood
   - ID sorting for cache keys, dood
   - API request, dood

### Phase 4: Documentation (Priority: Medium)

9. **Create README.md**, dood:
   - Overview and features, dood
   - Installation instructions, dood
   - Usage examples, dood
   - API reference, dood

10. **Add module docstring**, dood:
    - Module purpose, dood
    - Quick start example, dood
    - Links to documentation, dood

### Phase 5: Testing (Priority: High)

11. **Create test files**, dood:
    - [`test_client.py`](lib/geocode_maps/test_client.py) - Unit tests, dood
    - [`test_integration.py`](lib/geocode_maps/test_integration.py) - Integration tests, dood
    - [`test_models.py`](lib/geocode_maps/test_models.py) - Model validation, dood

12. **Implement unit tests**, dood:
    - Mock HTTP responses, dood
    - Test cache behavior, dood
    - Test error handling, dood
    - Test rate limiting, dood

13. **Implement integration tests**, dood:
    - Real API calls (with test key), dood
    - End-to-end workflows, dood
    - Performance testing, dood

## Testing Strategy

### Unit Tests

**File**: [`lib/geocode_maps/test_client.py`](lib/geocode_maps/test_client.py)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from lib.geocode_maps import GeocodeMapsClient
from lib.cache import DictCache

@pytest.mark.asyncio
async def test_search_with_cache_hit():
    """Test search with cached result, dood!"""
    # Setup
    cache = DictCache()
cache)
    
    # Pre-populate cache
    mockResult = [{"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}]
    await cache.set("search:test query:10:::false", mockResult)
    
    # Execute
    result = await client.search("Test Query")
    
    # Verify
    assert result == mockResult
    # Should not make HTTP request (verify via logs or mock)

@pytest.mark.asyncio
async def test_search_with_cache_miss():
    """Test search with API call, dood!"""
    # Setup
    cache = DictCache()
    client = GeocodeMapsClient(apiKey="test_key", searchCache=cache)
    
    mockResponse = [{"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}]
    
    with patch.object(client, '_makeRequest', return_value=mockResponse) as mock_request:
        # Execute
        result = await client.search("Test Query")
        
        # Verify
        assert result == mockResponse
        mock_request.assert_called_once()
        
        # Verify cached
        cached = await cache.get("search:test query:10:::false")
        assert cached == mockResponse

@pytest.mark.asyncio
async def test_reverse_coordinate_rounding():
    """Test coordinate rounding for cache keys, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")
    
    # Test rounding
    key1 = client._buildCacheKey("reverse", round(52.54432, 4), round(103.88821, 4), None)
    key2 = client._buildCacheKey("reverse", round(52.54435, 4), round(103.88825, 4), None)
    
    # Should produce same key (rounded to 4 decimals)
    assert key1 == key2 == "reverse:52.5443:103.8882:None"

@pytest.mark.asyncio
async def test_error_handling_401():
    """Test handling of authentication error, dood!"""
    client = GeocodeMapsClient(apiKey="invalid_key")
    
    with patch('httpx.AsyncClient') as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
        
        result = await client.search("Test")
        
        assert result is None

@pytest.mark.asyncio
async def test_rate_limiting():
    """Test rate limiter integration, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")
    
    with patch.object(client._rateLimiter, 'applyLimit') as mock_limit:
        with patch.object(client, '_makeRequest', return_value=[]):
            await client.search("Test")
            
            # Verify rate limiter was called
            mock_limit.assert_called_once_with("geocode-maps")
```

### Integration Tests

**File**: [`lib/geocode_maps/test_integration.py`](lib/geocode_maps/test_integration.py)

```python
import pytest
import os
from lib.geocode_maps import GeocodeMapsClient
from lib.cache import DictCache

# Skip if no API key available
pytestmark = pytest.mark.skipif(
    not os.getenv("GEOCODE_MAPS_API_KEY"),
    reason="GEOCODE_MAPS_API_KEY not set"
)

@pytest.mark.asyncio
async def test_real_search():
    """Test real search request, dood!"""
    apiKey = os.getenv("GEOCODE_MAPS_API_KEY")
    client = GeocodeMapsClient(apiKey=apiKey)
    
    results = await client.search("Angarsk, Russia", limit=1)
    
    assert results is not None
    assert len(results) > 0
    assert "Angarsk" in results[0]["display_name"]
    assert results[0]["address"]["country_code"] == "ru"

@pytest.mark.asyncio
async def test_real_reverse():
    """Test real reverse geocoding, dood!"""
    apiKey = os.getenv("GEOCODE_MAPS_API_KEY")
    client = GeocodeMapsClient(apiKey=apiKey)
    
    # Angarsk coordinates
    result = await client.reverse(52.5443, 103.8882)
    
    assert result is not None
    assert "Angarsk" in result["display_name"]
    assert result["address"]["country_code"] == "ru"

@pytest.mark.asyncio
async def test_real_lookup():
    """Test real OSM lookup, dood!"""
    apiKey = os.getenv("GEOCODE_MAPS_API_KEY")
    client = GeocodeMapsClient(apiKey=apiKey)
    
    # Angarsk OSM relation ID
    results = await client.lookup(["R2623018"])
    
    assert results is not None
    assert len(results) > 0
    assert results[0]["name"] == "Ангарск"

@pytest.mark.asyncio
async def test_caching_behavior():
    """Test that caching works correctly, dood!"""
    apiKey = os.getenv("GEOCODE_MAPS_API_KEY")
    cache = DictCache()
    client = GeocodeMapsClient(apiKey=apiKey, searchCache=cache)
    
    # First request - should hit API
    result1 = await client.search("Angarsk, Russia", limit=1)
    
    # Second request - should hit cache
    result2 = await client.search("Angarsk, Russia", limit=1)
    
    # Results should be identical
    assert result1 == result2
    
    # Verify cache was used
    stats = cache.getStats()
    assert stats["entries"] > 0
```

### Model Tests

**File**: [`lib/geocode_maps/test_models.py`](lib/geocode_maps/test_models.py)

```python
import pytest
from lib.geocode_maps.models import (
    SearchResult,
    ReverseResult,
    LookupResult,
    Address,
    NameDetails,
    ExtraTags,
)

def test_search_result_structure():
    """Test SearchResult TypedDict structure, dood!"""
    result: SearchResult = {
        "place_id": 123,
        "licence": "ODbL",
        "osm_type": "relation",
        "osm_id": 2623018,
        "lat": "52.5443",
        "lon": "103.8882",
        "category": "place",
        "type": "city",
        "place_rank": 16,
        "importance": 0.548,
        "addresstype": "city",
        "name": "Angarsk",
        "display_name": "Angarsk, Russia",
        "address": {
            "city": "Angarsk",
            "country": "Russia",
            "country_code": "ru"
        },
        "boundingbox": ["52.43", "52.62", "103.79", "104.00"]
    }
    
    # Verify required fields
    assert result["place_id"] == 123
    assert result["name"] == "Angarsk"
    assert result["lat"] == "52.5443"

def test_address_optional_fields():
    """Test Address with optional fields, dood!"""
    address: Address = {
        "city": "Angarsk",
        "country": "Russia"
    }
    
    # Should work with minimal fields
    assert address["city"] == "Angarsk"
    assert "road" not in address  # Optional field
```

### Test Coverage Goals

- **Unit Tests**: >90% code coverage, dood
- **Integration Tests**: All public methods with real API, dood
- **Model Tests**: Validate TypedDict structures, dood
- **Error Cases**: All error paths tested, dood

## References

### Internal Documentation

- [`docs/design/geocode-maps-client-design-v0.md`](docs/design/geocode-maps-client-design-v0.md) - Original requirements, dood
- [`docs/other/geocode-maps/Geocode-Maps-API.md`](docs/other/geocode-maps/Geocode-Maps-API.md) - API reference documentation, dood
- [`lib/openweathermap/client.py`](lib/openweathermap/client.py) - Reference implementation pattern, dood
- [`lib/yandex_search/client.py`](lib/yandex_search/client.py) - Reference implementation pattern, dood
- [`lib/cache/interface.py`](lib/cache/interface.py) - Cache interface documentation, dood
- [`lib/rate_limiter/manager.py`](lib/rate_limiter/manager.py) - Rate limiter documentation, dood

### Example Responses

- [`docs/other/geocode-maps/search-Angarsk-jsonv2.json`](docs/other/geocode-maps/search-Angarsk-jsonv2.json) - Search endpoint example, dood
- [`docs/other/geocode-maps/reverse-Angarsk-jsonv2.json`](docs/other/geocode-maps/reverse-Angarsk-jsonv2.json) - Reverse endpoint example, dood
- [`docs/other/geocode-maps/lookup-Angarsk-jsonv2.json`](docs/other/geocode-maps/lookup-Angarsk-jsonv2.json) - Lookup endpoint example, dood

### External Resources

- [Geocode Maps API Documentation](https://geocode.maps.co/docs/endpoints/) - Official API docs, dood
- [OpenStreetMap Wiki](https://wiki.openstreetmap.org/) - OSM data reference, dood

## Architecture Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        Client[GeocodeMapsClient]
    end
    
    subgraph "Public Methods"
        Search[search]
        Reverse[reverse]
        Lookup[lookup]
    end
    
    subgraph "Internal Methods"
        MakeRequest[_makeRequest]
        BuildKey[_buildCacheKey]
    end
    
    subgraph "External Dependencies"
        Cache[Cache Interface]
        RateLimiter[Rate Limiter Manager]
        HTTP[httpx AsyncClient]
    end
    
    subgraph "API Endpoints"
        SearchAPI[/search]
        ReverseAPI[/reverse]
        LookupAPI[/lookup]
    end
    
    Client --> Search
    Client --> Reverse
    Client --> Lookup
    
    Search --> BuildKey
    Reverse --> BuildKey
    Lookup --> BuildKey
    
    Search --> Cache
    Reverse --> Cache
    Lookup --> Cache
    
    Search --> MakeRequest
    Reverse --> MakeRequest
    Lookup --> MakeRequest
    
    MakeRequest --> RateLimiter
    MakeRequest --> HTTP
    
    HTTP --> SearchAPI
    HTTP --> ReverseAPI
    HTTP --> LookupAPI
    
    style Client fill:#e1f5ff
    style Cache fill:#fff4e1
    style RateLimiter fill:#fff4e1
    style HTTP fill:#fff4e1
```

## Summary

This design document provides a comprehensive blueprint for implementing a production-ready Geocode Maps API client that follows established patterns in the codebase, dood!

### Key Features

✅ **Type Safety**: Comprehensive TypedDict models with full type hints, dood  
✅ **Performance**: Multi-level caching with configurable TTL, dood  
✅ **Reliability**: Rate limiting and robust error handling, dood  
✅ **Consistency**: Follows patterns from existing clients, dood  
✅ **Maintainability**: Clear architecture and comprehensive documentation, dood  
✅ **Testability**: Complete test strategy with unit and integration tests, dood  

### Next Steps

1. Review and approve this design document, dood
2. Create implementation plan with task breakdown, dood
3. Implement Phase 1 (Core Structure), dood
4. Implement Phase 2 (Core Functionality), dood
5. Implement Phase 3 (Additional Endpoints), dood
6. Implement Phase 4 (Documentation), dood
7. Implement Phase 5 (Testing), dood
8. Code review and refinement, dood
9. Integration with existing systems, dood
10. Production deployment, dood

### Questions for Review

1. **Cache TTL**: Are 30-day TTLs appropriate for all endpoint types, dood?
2. **Rate Limiting**: Should we start with 1 req/sec or higher, dood?
3. **Language Support**: Should we support per-request language override, dood?
4. **Polygon Data**: Should we add convenience methods for polygon handling, dood?
5. **Batch Operations**: Should we add batch lookup support in v1, dood?

---

**Document Status**: Ready for Review, dood! 🎉
    client = GeocodeMapsClient(apiKey="test_key", searchCache=