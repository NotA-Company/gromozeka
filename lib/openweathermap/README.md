# OpenWeatherMap Async Client Library

A comprehensive async client library for the OpenWeatherMap API with database-backed caching, designed for the Gromozeka Telegram bot project.

## Features

- 🌍 **Geocoding Support**: Convert city names to coordinates
- 🌤️ **Weather Data**: Current weather and daily forecasts
- 💾 **Database Caching**: Persistent caching with configurable TTL
- 🚀 **Async/Await**: Full async support for high performance
- 🔧 **Configurable**: Flexible configuration options
- 🌐 **Multi-language**: Support for different languages (Russian, English, etc.)
- 🛡️ **Error Handling**: Robust error handling and logging
- 🧪 **Well Tested**: Comprehensive test suite

## Quick Start

### Basic Usage

```python
from lib.openweathermap import OpenWeatherMapClient, DatabaseWeatherCache
from internal.database.wrapper import DatabaseWrapper

# Initialize database and cache
db = DatabaseWrapper("gromozeka.db")
cache = DatabaseWeatherCache(db)

# Create client
async with OpenWeatherMapClient(
    api_key="your_openweathermap_api_key",
    cache=cache
) as client:
    # Get weather for a city
    result = await client.getWeatherByCity("Moscow", "RU")
    
    if result:
        location = result['location']
        weather = result['weather']
        current = weather['current']
        
        print(f"🌍 {location['name']}: {current['temp']}°C")
        print(f"🌤️ {current['weather_description']}")
```

### Step-by-Step Usage

```python
# Get coordinates first
location = await client.getCoordinates("London", "GB")
if location:
    print(f"📍 {location['name']}: {location['lat']}, {location['lon']}")
    
    # Then get weather
    weather = await client.getWeather(location['lat'], location['lon'])
    if weather:
        print(f"🌡️ Temperature: {weather['current']['temp']}°C")
```

## Configuration

### Default Configuration

Add to your `config.toml`:

```toml
[openweathermap]
# OpenWeatherMap API key from https://openweathermap.org/api
api-key = "YOUR_OPENWEATHERMAP_API_KEY"

# Cache time-to-live in seconds
geocoding-cache-ttl = 2592000  # 30 days (coordinates rarely change)
weather-cache-ttl = 3600       # 60 minutes (weather updates frequently)

# API request timeout in seconds
request-timeout = 10

# Default language for location names (ru, en, etc.)
default-language = "ru"
```

### Using Configuration Manager

```python
from internal.config.manager import ConfigManager

config = ConfigManager()
weather_config = config.getOpenWeatherMapConfig()

async with OpenWeatherMapClient(
    api_key=weather_config['api-key'],
    cache=cache,
    geocoding_ttl=weather_config.get('geocoding-cache-ttl', 2592000),
    weather_ttl=weather_config.get('weather-cache-ttl', 3600),
    request_timeout=weather_config.get('request-timeout', 10),
    default_language=weather_config.get('default-language', 'ru')
) as client:
    # Use client...
```

## API Reference

### OpenWeatherMapClient

Main client class for interacting with the OpenWeatherMap API.

#### Constructor

```python
OpenWeatherMapClient(
    api_key: str,
    cache: WeatherCacheInterface,
    geocoding_ttl: int = 2592000,  # 30 days
    weather_ttl: int = 1800,       # 30 minutes
    request_timeout: int = 10,
    default_language: str = "ru"
)
```

#### Methods

##### `getCoordinates(city, country=None, state=None, limit=1)`

Get coordinates by city name.

**Parameters:**
- `city` (str): City name (e.g., "Moscow", "London")
- `country` (str, optional): Country code (e.g., "RU", "GB")
- `state` (str, optional): State code (for US cities)
- `limit` (int): Max results (default 1)

**Returns:** `GeocodingResult` or `None`

**Example:**
```python
location = await client.getCoordinates("Moscow", "RU")
# Returns: {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, ...}
```

##### `getWeather(lat, lon, exclude=None)`

Get weather data by coordinates.

**Parameters:**
- `lat` (float): Latitude
- `lon` (float): Longitude
- `exclude` (list, optional): Parts to exclude (default: ["minutely", "hourly", "alerts"])

**Returns:** `WeatherData` or `None`

**Example:**
```python
weather = await client.getWeather(55.7558, 37.6173)
# Returns: {"current": {"temp": 15.5, ...}, "daily": [...], ...}
```

##### `getWeatherByCity(city, country=None, state=None)`

Combined operation: get coordinates then get weather.

**Parameters:**
- `city` (str): City name
- `country` (str, optional): Country code
- `state` (str, optional): State code

**Returns:** `CombinedWeatherResult` or `None`

**Example:**
```python
result = await client.getWeatherByCity("Moscow", "RU")
# Returns: {"location": {...}, "weather": {...}}
```

### Data Models

#### GeocodingResult

```python
{
    "name": str,              # City name (English)
    "local_names": dict,      # Names in different languages
    "lat": float,             # Latitude
    "lon": float,             # Longitude
    "country": str,           # Country code
    "state": Optional[str]    # State/region name
}
```

#### WeatherData

```python
{
    "lat": float,
    "lon": float,
    "timezone": str,
    "current": CurrentWeather,
    "daily": List[DailyWeather]  # Up to 8 days
}
```

#### CurrentWeather

```python
{
    "dt": int,                    # Unix timestamp
    "temp": float,                # Temperature (Celsius)
    "feels_like": float,          # Feels like temperature
    "pressure": int,              # Atmospheric pressure (hPa)
    "humidity": int,              # Humidity percentage
    "clouds": int,                # Cloudiness percentage
    "wind_speed": float,          # Wind speed (m/s)
    "wind_deg": int,              # Wind direction (degrees)
    "weather_id": int,            # Weather condition ID
    "weather_main": str,          # Weather group
    "weather_description": str    # Weather description
}
```

## Caching

The library uses a two-tier caching system:

### Cache Types

1. **Geocoding Cache**: Stores city → coordinates mappings
   - Default TTL: 30 days (coordinates rarely change)
   - Cache key format: `"city,country,state"` (normalized lowercase)

2. **Weather Cache**: Stores coordinates → weather data
   - Default TTL: 60 minutes (weather updates frequently)
   - Cache key format: `"lat,lon"` (rounded to 4 decimal places)

### Cache Interface

The `WeatherCacheInterface` allows for different cache implementations:

```python
class WeatherCacheInterface(ABC):
    async def get(self, key: str, cache_type: str) -> Optional[str]
    async def set(self, key: str, cache_type: str, data: str) -> bool
    async def isExpired(self, key: str, cache_type: str, ttl_seconds: int) -> bool
    async def clearExpired(self, cache_type: str, ttl_seconds: int) -> int
    async def clearAll(self, cache_type: Optional[str] = None) -> bool
```

### Database Cache

The `DatabaseWeatherCache` implementation uses the project's SQLite database:

```python
# Tables created automatically:
# - geocoding_cache (cache_key, data, created_at, updated_at)
# - weather_cache (cache_key, data, created_at, updated_at)

cache = DatabaseWeatherCache(db_wrapper)
```

## Error Handling

The client handles various error scenarios gracefully:

### API Errors
- **401 Unauthorized**: Invalid API key → logs error, returns None
- **404 Not Found**: City not found → logs warning, returns None
- **429 Too Many Requests**: Rate limit → logs error, returns cached data if available
- **500+ Server Errors**: OpenWeatherMap issues → logs error, returns cached data if available

### Network Errors
- **Timeout**: Logs error, returns cached data if available
- **Connection Error**: Logs error, returns cached data if available
- **DNS Error**: Logs error, returns None

### Cache Errors
- **Database Error**: Logs error, continues without cache (direct API call)
- **JSON Parse Error**: Logs error, invalidates cache entry

## Bot Integration

### Command Handler Example

```python
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weather command"""
    city = context.args[0] if context.args else "Moscow"
    
    # Get weather
    result = await weather_client.getWeatherByCity(city)
    
    if result:
        location = result['location']
        weather = result['weather']
        current = weather['current']
        
        # Format message
        message = f"""
🌍 **{location['name']}, {location['country']}**
{location['local_names'].get('ru', '')}

🌡️ **Температура:** {current['temp']}°C (ощущается как {current['feels_like']}°C)
☁️ **Облачность:** {current['clouds']}%
💨 **Ветер:** {current['wind_speed']} м/с
💧 **Влажность:** {current['humidity']}%
📊 **Давление:** {current['pressure']} гПа

{current['weather_description']}
"""
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("Город не найден, dood!")
```

## Testing

Run the test suite:

```bash
# Run all tests
./venv/bin/python3 -m pytest lib/openweathermap/test_weather_client.py -v

# Run specific test class
./venv/bin/python3 -m pytest lib/openweathermap/test_weather_client.py::TestOpenWeatherMapClient -v

# Run with coverage
./venv/bin/python3 -m pytest lib/openweathermap/test_weather_client.py --cov=lib.openweathermap
```

### Test Coverage

The test suite includes:
- ✅ Unit tests for OpenWeatherMapClient
- ✅ Unit tests for DatabaseWeatherCache
- ✅ Integration tests
- ✅ Error handling tests
- ✅ Cache behavior tests
- ✅ API response parsing tests

## Examples

See `examples.py` for comprehensive usage examples:

```bash
./venv/bin/python3 lib/openweathermap/examples.py
```

Examples include:
- Basic usage
- Step-by-step operations
- Multiple cities
- Cache demonstration
- Error handling
- Bot integration
- Configuration options

## Performance Considerations

### Caching Strategy
- **Geocoding**: 30-day TTL (coordinates rarely change)
- **Weather**: 60-minute TTL (balance freshness vs API calls)
- **Cache key normalization**: Lowercase, trimmed, consistent format
- **Coordinate rounding**: 4 decimal places (~11m precision)

### Database Optimization
- **Indexes**: Created on `updated_at` for fast expiration queries
- **Primary keys**: Fast lookups on `cache_key`
- **Periodic cleanup**: Remove expired entries (can be scheduled)

### API Rate Limits
OpenWeatherMap free tier:
- 60 calls/minute
- 1,000,000 calls/month

The caching strategy keeps usage well within limits for typical bot usage.

## Getting an API Key

1. Go to [OpenWeatherMap](https://openweathermap.org/api)
2. Sign up for a free account
3. Generate an API key
4. Add it to your `config.toml`

The free tier includes:
- Current weather data
- 5-day/3-hour forecast
- Geocoding API
- 60 calls/minute, 1,000,000 calls/month

## Dependencies

The library uses these dependencies (already in the project):
- `aiohttp` - Async HTTP client
- `json` - JSON parsing
- `logging` - Logging support
- `datetime` - Date/time handling
- `typing` - Type hints

## Architecture

The library follows the project's established patterns:

```
lib/openweathermap/
├── __init__.py              # Module exports
├── models.py                # Data models (TypedDicts)
├── cache_interface.py       # Abstract cache interface
├── database_cache.py        # Database cache implementation
├── client.py                # Main client class
├── test_weather_client.py   # Test suite
├── examples.py              # Usage examples
└── README.md                # This documentation
```

### Design Patterns Used
- **Abstract Factory**: Cache interface allows different implementations
- **Template Method**: Client provides common API request handling
- **Strategy**: Different cache strategies (database, memory, etc.)
- **Facade**: Simple interface hiding complex API interactions

## Contributing

When contributing to this library:

1. Follow the project's camelCase naming convention
2. Add comprehensive tests for new features
3. Update documentation and examples
4. Use the project's logging patterns
5. Follow the existing error handling patterns

## License

This library is part of the Gromozeka project and follows the same license terms.