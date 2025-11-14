# Geocode Maps API Client

Async Python client for the Geocode Maps API (geocode.maps.co) with built-in caching and rate limiting, dood!

## Features

- **Type-Safe**: Full TypedDict models with comprehensive type hints
- **Async/Await**: Built on httpx for efficient async operations
- **Caching**: Configurable caching with separate TTLs per endpoint
- **Rate Limiting**: Integrated rate limiting to prevent API quota exhaustion
- **Error Handling**: Graceful error handling with detailed logging
- **Three Endpoints**: Forward geocoding, reverse geocoding, and OSM lookup

## Installation

This library is part of the gromozeka project. Ensure you have the required dependencies:

```bash
pip install httpx
```

## Quick Start

### Basic Usage

```python
from lib.geocode_maps import GeocodeMapsClient
from lib.cache import DictCache

# Initialize client with caching
client = GeocodeMapsClient(
    apiKey="your_api_key_here",
    searchCache=DictCache(),
    reverseCache=DictCache(),
    lookupCache=DictCache(),
    acceptLanguage="en"
)

# Forward geocoding (address → coordinates)
results = await client.search("Angarsk, Russia", limit=5)
if results:
    first = results[0]
    print(f"Found: {first['display_name']}")
    print(f"Coordinates: {first['lat']}, {first['lon']}")

# Reverse geocoding (coordinates → address)
location = await client.reverse(52.5443, 103.8882)
if location:
    print(f"Address: {location['display_name']}")
    print(f"City: {location['address'].get('city', 'N/A')}")

# OSM object lookup
places = await client.lookup(["R2623018"])
if places:
    place = places[0]
    print(f"Place: {place['name']}")
    print(f"Type: {place['type']}")
```

### Advanced Configuration

```python
from lib.geocode_maps import GeocodeMapsClient
from lib.cache import DictCache

client = GeocodeMapsClient(
    apiKey="your_api_key",
    searchCache=DictCache(),
    reverseCache=DictCache(),
    lookupCache=DictCache(),
    searchTTL=2592000,      # 30 days
    reverseTTL=2592000,     # 30 days
    lookupTTL=2592000,      # 30 days
    requestTimeout=10,      # 10 seconds
    acceptLanguage="ru",    # Russian language
    rateLimiterQueue="geocode-maps"
)
```

## API Methods

### search()

Forward geocoding: convert address to coordinates.

```python
results = await client.search(
    query="Angarsk, Russia",
    limit=10,
    countrycodes="ru",
    addressdetails=True,
    extratags=True,
    namedetails=True
)
```

**Parameters:**
- `query` (str): Free-form search query
- `limit` (int): Maximum results (0-40, default: 10)
- `countrycodes` (str, optional): Comma-separated country codes
- `viewbox` (str, optional): Bounding box to bias search
- `bounded` (bool): Restrict results to viewbox (default: False)
- `addressdetails` (bool): Include structured address (default: True)
- `extratags` (bool): Include extra OSM tags (default: True)
- `namedetails` (bool): Include name translations (default: True)
- `dedupe` (bool): Remove duplicates (default: True)

**Returns:** `Optional[SearchResponse]` - List of search results or None

### reverse()

Reverse geocoding: convert coordinates to address.

```python
location = await client.reverse(
    lat=52.5443,
    lon=103.8882,
    zoom=18,
    addressdetails=True,
    extratags=True,
    namedetails=True
)
```

**Parameters:**
- `lat` (float): Latitude (-90 to 90)
- `lon` (float): Longitude (-180 to 180)
- `zoom` (int, optional): Detail level (3-18, higher = more detailed)
- `addressdetails` (bool): Include structured address (default: True)
- `extratags` (bool): Include extra OSM tags (default: True)
- `namedetails` (bool): Include name translations (default: True)

**Returns:** `Optional[ReverseResponse]` - Reverse geocoding result or None

### lookup()

Lookup OSM objects by ID.

```python
places = await client.lookup(
    osmIds=["R2623018", "N107775"],
    addressdetails=True,
    extratags=True,
    namedetails=True,
    polygonText=True
)
```

**Parameters:**
- `osmIds` (List[str]): OSM IDs with type prefix (N/W/R)
- `addressdetails` (bool): Include structured address (default: True)
- `extratags` (bool): Include extra OSM tags (default: True)
- `namedetails` (bool): Include name translations (default: True)
- `polygonGeojson` (bool): Include GeoJSON polygon (default: False)
- `polygonKml` (bool): Include KML polygon (default: False)
- `polygonSvg` (bool): Include SVG polygon (default: False)
- `polygonText` (bool): Include WKT polygon (default: False)

**Returns:** `Optional[LookupResponse]` - List of lookup results or None

## Data Models

All response models are TypedDict classes for type safety:

- `SearchResult`: Single search result with coordinates and address
- `ReverseResult`: Reverse geocoding result
- `LookupResult`: OSM object lookup result
- `Address`: Structured address components
- `NameDetails`: Name translations in different languages
- `ExtraTags`: Additional OSM tags and metadata

See [`lib/geocode_maps/models.py`](lib/geocode_maps/models.py) for complete model definitions.

## Caching

The client uses separate cache instances for each endpoint:

- **Search Cache**: Caches forward geocoding results
- **Reverse Cache**: Caches reverse geocoding results (coordinates rounded to 4 decimals)
- **Lookup Cache**: Caches OSM object lookups

Default TTL is 30 days (2,592,000 seconds) for all endpoints.

### Cache Key Format

- Search: `search:{query}:{limit}:{countrycodes}:{viewbox}:{bounded}`
- Reverse: `reverse:{lat_rounded}:{lon_rounded}:{zoom}`
- Lookup: `lookup:{sorted_osm_ids}:{polygon_flags}`

## Rate Limiting

The client integrates with the rate limiter manager using the queue name `geocode-maps` by default.

Configure rate limiting at application startup:

```python
from lib.rate_limiter import RateLimiterManager, SlidingWindowRateLimiter, QueueConfig

manager = RateLimiterManager.getInstance()
limiter = SlidingWindowRateLimiter(
    QueueConfig(maxRequests=60, windowSeconds=60)
)
await limiter.initialize()
manager.registerRateLimiter("geocode-maps-limiter", limiter)
manager.bindQueue("geocode-maps", "geocode-maps-limiter")
```

## Error Handling

All methods return `Optional[T]` and never raise exceptions. Errors are logged:

- **401**: Invalid API key (error log)
- **404**: Location not found (warning log)
- **429**: Rate limit exceeded (error log)
- **5xx**: Server error (error log)
- **Timeout**: Request timeout (error log)
- **Network**: Connection error (error log)

Check return value for None to detect errors:

```python
result = await client.search("Invalid Query")
if result is None:
    print("Search failed - check logs for details")
```

## Testing

Run tests with pytest:

```bash
# Unit tests
pytest lib/geocode_maps/test_client.py -v

# Integration tests (requires API key)
export GEOCODE_MAPS_API_KEY="your_api_key"
pytest lib/geocode_maps/test_integration.py -v

# Model tests
pytest lib/geocode_maps/test_models.py -v
```

## Design Documentation

For detailed design decisions and architecture, see:
- [`docs/design/geocode-maps-client-design-v1.md`](docs/design/geocode-maps-client-design-v1.md)
- [`docs/other/Geocode-Maps-API.md`](docs/other/Geocode-Maps-API.md)

## License

Part of the gromozeka project.