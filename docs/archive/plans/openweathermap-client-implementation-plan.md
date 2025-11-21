
# OpenWeatherMap Async Client Implementation Plan

**Task ID:** TBD  
**Created:** 2025-10-18  
**Status:** Planning Phase  
**Estimated Complexity:** Medium  

---

## 1. Overview

Yo, dood! This plan outlines the implementation of an async OpenWeatherMap API client for the Gromozeka Telegram bot. The client will provide geocoding (city name → coordinates) and weather data retrieval with database-backed caching and configurable TTL.

### 1.1 Goals

- Create async OpenWeatherMap client class with clean API
- Implement geocoding API integration (city name (+optional country) → coordinates)
- Implement weather API integration (coordinates → weather data)
- Add database-backed caching with TTL support
- Follow existing project patterns (similar to Bayes filter architecture)
- Provide combined method for sequential operations

### 1.2 Non-Goals

- Weather forecasting beyond current + daily data
- Historical weather data
- Weather alerts/warnings
- Multiple weather data providers

---

## 2. Architecture Design

### 2.1 Module Structure

Following the existing project patterns (lib/spam/, lib/ai/), we'll create:

```
lib/openweathermap/
├── __init__.py              # Module exports
├── models.py                # Data models (TypedDicts, dataclasses)
├── cache_interface.py       # Abstract cache interface
├── database_cache.py        # Database cache implementation
├── client.py # Main client class
└── test_weather_client.py   # Test suite
```

### 2.2 Database Schema

Add new tables to [`internal/database/wrapper.py`](internal/database/wrapper.py):

```sql
CREATE TABLE IF NOT EXISTS geocoding_cache (
    cache_key TEXT PRIMARY KEY, -- City+optional country code
    data TEXT NOT NULL,         -- JSON-serialized response
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weather_cache (
    cache_key TEXT PRIMARY KEY, -- lat:lon
    data TEXT NOT NULL,         -- JSON-serialized response
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.3 Configuration

Add to [`configs/00-defaults/config.toml`](configs/00-defaults/config.toml):

```toml
[openweathermap]
# OpenWeatherMap API key
api-key = "YOUR_OPENWEATHERMAP_API_KEY"

# Cache TTL in seconds
geocoding-cache-ttl = 2592000  # 30 days (coordinates rarely change)
weather-cache-ttl = 1800       # 30 minutes (weather updates frequently)

# API request timeout in seconds
request-timeout = 10

# Default language for location names
default-language = "ru"  # Russian names when available
```

---

## 3. Detailed Component Design

### 3.1 Data Models (`lib/openweathermap/models.py`)

```python
from typing import Optional, TypedDict
from dataclasses import dataclass
import datetime

# API Response Models
class GeocodingResult(TypedDict):
    """Result from geocoding API"""
    name: str              # City name (English)
    local_names: dict      # Names in different languages {"ru": "Москва", "en": "Moscow"}
    lat: float             # Latitude
    lon: float             # Longitude
    country: str           # Country code (e.g., "RU")
    state: Optional[str]   # State/region name (if available)

class CurrentWeather(TypedDict):
    """Current weather data"""
    dt: int                # Unix timestamp
    temp: float            # Temperature (Celsius)
    feels_like: float      # Feels like temperature
    pressure: int          # Atmospheric pressure (hPa)
    humidity: int          # Humidity percentage
    clouds: int            # Cloudiness percentage
    wind_speed: float      # Wind speed (m/s)
    wind_deg: int          # Wind direction (degrees)
    weather_id: int        # Weather condition ID
    weather_main: str      # Weather group (Rain, Snow, Clear, etc.)
    weather_description: str  # Weather description

class DailyWeather(TypedDict):
    """Daily weather forecast"""
    dt: int                # Unix timestamp
    temp_day: float        # Day temperature
    temp_min: float        # Min temperature
    temp_max: float        # Max temperature
    pressure: int          # Atmospheric pressure
    humidity: int          # Humidity percentage
    wind_speed: float      # Wind speed
    clouds: int            # Cloudiness percentage
    weather_id: int        # Weather condition ID
    weather_main: str      # Weather group
    weather_description: str  # Weather description
    pop: float             # Probability of precipitation (0-1)

class WeatherData(TypedDict):
    """Complete weather response"""
    lat: float
    lon: float
    timezone: str
    current: CurrentWeather
    daily: list[DailyWeather]  # Up to 8 days

class CombinedWeatherResult(TypedDict):
    """Combined geocoding + weather result"""
    location: GeocodingResult
    weather: WeatherData

# Cache Models
class CacheDict(TypedDict):
    """Database cache entry"""
    cache_key: str
    cache_type: str        # 'geocoding' or 'weather'
    data: str              # JSON string
    created_at: datetime.datetime
    updated_at: datetime.datetime
```

### 3.2 Cache Interface (`lib/openweathermap/cache_interface.py`)

Following the pattern from [`lib/spam/storage_interface.py`](lib/spam/storage_interface.py):

```python
from abc import ABC, abstractmethod
from typing import Optional
import datetime

class WeatherCacheInterface(ABC):
    """Abstract interface for weather data caching"""
    
    @abstractmethod
    async def get(self, key: str, cache_type: str) -> Optional[str]:
        """
        Get cached data by key
        
        Args:
            key: Cache key (e.g., "Moscow,RU" or "55.7558,37.6173")
            cache_type: Type of cache ('geocoding' or 'weather')
            
        Returns:
            JSON string if found and not expired, None otherwise
        """
        pass
    
    @abstractmethod
    async def set(self, key: str, cache_type: str, data: str) -> bool:
        """
        Store data in cache
        
        Args:
            key: Cache key
            cache_type: Type of cache
            data: JSON string to store
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def is_expired(self, key: str, cache_type: str, ttl_seconds: int) -> bool:
        """
        Check if cache entry is expired
        
        Args:
            key: Cache key
            cache_type: Type of cache
            ttl_seconds: Time-to-live in seconds
            
        Returns:
            True if expired or not found, False if still valid
        """
        pass
    
    @abstractmethod
    async def clear_expired(self, cache_type: str, ttl_seconds: int) -> int:
        """
        Remove expired cache entries
        
        Args:
            cache_type: Type of cache to clean
            ttl_seconds: TTL threshold
            
        Returns:
            Number of entries removed
        """
        pass
    
    @abstractmethod
    async def clear_all(self, cache_type: Optional[str] = None) -> bool:
        """
        Clear all cache entries
        
        Args:
            cache_type: Optional type filter (None = clear all types)
            
        Returns:
            True if successful
        """
        pass
```

### 3.3 Database Cache Implementation (`lib/openweathermap/database_cache.py`)

```python
import json
import logging
from typing import Optional
from datetime import datetime, timedelta
from .cache_interface import WeatherCacheInterface

class DatabaseWeatherCache(WeatherCacheInterface):
    """Database-backed weather cache implementation"""
    
    def __init__(self, db_wrapper):
        """
        Initialize cache with database wrapper
        
        Args:
            db_wrapper: DatabaseWrapper instance from internal.database.wrapper
        """
        self.db = db_wrapper
        self.logger = logging.getLogger(__name__)
    
    async def get(self, key: str, cache_type: str) -> Optional[str]:
        """Get cached data if exists and not expired"""
        # Implementation will query weather_cache table
        pass
    
    async def set(self, key: str, cache_type: str, data: str) -> bool:
        """Store data with INSERT OR REPLACE"""
        # Implementation will use INSERT OR REPLACE INTO weather_cache
        pass
    
    async def is_expired(self, key: str, cache_type: str, ttl_seconds: int) -> bool:
        """Check if entry exists and is within TTL"""
        # Implementation will check updated_at timestamp
        pass
    
    async def clear_expired(self, cache_type: str, ttl_seconds: int) -> int:
        """Remove entries older than TTL"""
        # Implementation will DELETE WHERE updated_at < (now - ttl)
        pass
    
    async def clear_all(self, cache_type: Optional[str] = None) -> bool:
        """Clear all or specific type"""
        # Implementation will DELETE with optional WHERE cache_type = ?
        pass
```

### 3.4 Main Client (`lib/openweathermap/client.py`)

```python
import aiohttp
import json
import logging
from typing import Optional, List
from .models import GeocodingResult, WeatherData, CombinedWeatherResult
from .cache_interface import WeatherCacheInterface

class OpenWeatherMapClient:
    """
    Async client for OpenWeatherMap API with caching
    
    Example usage:
        cache = DatabaseWeatherCache(db_wrapper)
        client = OpenWeatherMapClient(
            api_key="your_key",
            cache=cache,
            geocoding_ttl=2592000,  # 30 days
            weather_ttl=1800         # 30 minutes
        )
        
        # Get coordinates
        location = await client.get_coordinates("Moscow", "RU")
        
        # Get weather
        weather = await client.get_weather(55.7558, 37.6173)
        
        # Combined operation
        result = await client.get_weather_by_city("Moscow", "RU")
    """
    
    GEOCODING_API = "http://api.openweathermap.org/geo/1.0/direct"
    WEATHER_API = "https://api.openweathermap.org/data/3.0/onecall"
    
    def __init__(
        self,
        api_key: str,
        cache: WeatherCacheInterface,
        geocoding_ttl: int = 2592000,  # 30 days
        weather_ttl: int = 1800,        # 30 minutes
        request_timeout: int = 10,
        default_language: str = "ru"
    ):
        """
        Initialize OpenWeatherMap client
        
        Args:
            api_key: OpenWeatherMap API key
            cache: Cache implementation (must implement WeatherCacheInterface)
            geocoding_ttl: Cache TTL for geocoding results (seconds)
            weather_ttl: Cache TTL for weather data (seconds)
            request_timeout: HTTP request timeout (seconds)
            default_language: Default language for location names
        """
        self.api_key = api_key
        self.cache = cache
        self.geocoding_ttl = geocoding_ttl
        self.weather_ttl = weather_ttl
        self.request_timeout = request_timeout
        self.default_language = default_language
        self.logger = logging.getLogger(__name__)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.request_timeout))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def get_coordinates(
        self,
        city: str,
        country: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 1
    ) -> Optional[GeocodingResult]:
        """
        Get coordinates by city name
        
        Uses: http://api.openweathermap.org/geo/1.0/direct
        
        Args:
            city: City name (e.g., "Moscow", "London")
            country: Optional country code (e.g., "RU", "GB")
            state: Optional state code (for US cities)
            limit: Max results (default 1, we return first match)
            
        Returns:
            GeocodingResult with coordinates and names, or None if not found
            
        Cache key format: "city,country,state" (normalized lowercase)
        """
        # 1. Build cache key
        # 2. Check cache with geocoding_ttl
        # 3. If cache miss, make API request
        # 4. Parse response and extract first result
        # 5. Store in cache
        # 6. Return GeocodingResult
        pass
    
    async def get_weather(
        self,
        lat: float,
        lon: float,
        exclude: Optional[List[str]] = None
    ) -> Optional[WeatherData]:
        """
        Get weather data by coordinates
        
        Uses: https://api.openweathermap.org/data/3.0/onecall
        
        Args:
            lat: Latitude
            lon: Longitude
            exclude: Optional list of parts to exclude
                    (e.g., ["minutely", "hourly", "alerts"])
                    We'll default to excluding minutely, hourly, alerts
                    
        Returns:
            WeatherData with current and daily forecast, or None if error
            
        Cache key format: "lat,lon" (rounded to 4 decimal places)
        """
        # 1. Build cache key (round coordinates to 4 decimals)
        # 2. Check cache with weather_ttl
        # 3. If cache miss, make API request
        # 4. Parse response
        # 5. Store in cache
        # 6. Return WeatherData
        pass
    
    async def get_weather_by_city(
        self,
        city: str,
        country: Optional[str] = None,
        state: Optional[str] = None
    ) -> Optional[CombinedWeatherResult]:
        """
        Combined operation: get coordinates then get weather
        
        This is a convenience method that calls get_coordinates()
        followed by get_weather(). Both operations use their
        respective caches.
        
        Args:
            city: City name
            country: Optional country code
            state: Optional state code
            
        Returns:
            CombinedWeatherResult with location and weather data,
            or None if geocoding fails
        """
        # 1. Call get_coordinates()
        # 2. If successful, call get_weather() with returned coordinates
        # 3. Return combined result
        pass
    
    async def _make_request(self, url: str, params: dict) -> Optional[dict]:
        """
        Make HTTP request to OpenWeatherMap API
        
        Args:
            url: API endpoint URL
            params: Query parameters (api_key will be added automatically)
            
        Returns:
            Parsed JSON response or None on error
        """
        # 1. Add api_key to params
        # 2. Make GET request with aiohttp
        # 3. Handle errors (network, timeout, API errors)
        # 4. Parse JSON response
        # 5. Log errors appropriately
        pass
```

---

## 4. Database Integration

### 4.1 Add to DatabaseWrapper

In [`internal/database/wrapper.py`](internal/database/wrapper.py):

1. **Add table creation in `_create_tables()`:**
```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS geocoding_cache (
        cache_key TEXT PRIMARY KEY, -- City+optional country code
        data TEXT NOT NULL,         -- JSON-serialized response
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS weather_cache (
        cache_key TEXT PRIMARY KEY, -- lat:lon
        data TEXT NOT NULL,         -- JSON-serialized response
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
```

2. **Add validation method:**
```python
def _validateDictIsCacheDict(self, row_dict: Dict[str, Any]) -> CacheDict:
    """Validate and convert database row to CacheDict"""
    # Similar to existing _validateDictIsChatMessageDict pattern
    pass
```

3. **Add cache methods:**
```python
def getWeatherCache(self, key: str) -> Optional[CacheDict]:
    """Get weather cache entry"""
    pass

def setWeatherCache(self, key: str, data: str) -> bool:
    """Store weather cache entry (INSERT ON CONFLICT UPDATE)"""
    pass

def getGeocodingCache(self, key: str) -> Optional[CacheDict]:
    """Get geocoding cache entry"""
    pass

def setGeocodingCache(self, key: str, data: str) -> bool:
    """Store geocoding cache entry (INSERT ON CONFLICT UPDATE)"""
    pass

```

### 4.2 Add to models.py

In [`internal/database/models.py`](internal/database/models.py):

```python
class CacheDict(TypedDict):
    """Weather cache entry from database"""
    cache_key: str
    data: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
```

---

## 5. Configuration Integration

### 5.1 Update ConfigManager

In [`internal/config/manager.py`](internal/config/manager.py):

Add method to get weather configuration:

```python
def getOpenWeatherMapConfig(self) -> Dict[str, Any]:
    """
    Get OpenWeatherMap configuration
    
    Returns:
        Dict with OpenWeatherMap settings (api_key, ttls, etc.)
    """
    return self.config.get("openweathermap", {})
```

### 5.2 Update Default Config

In [`configs/00-defaults/config.toml`](configs/00-defaults/config.toml):

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

---

## 6. Testing Strategy

### 6.1 Unit Tests (`lib/openweathermap/test_weather_client.py`)

```python
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from .openweathermap_client import OpenWeatherMapClient
from .database_cache import DatabaseWeatherCache
from .models import GeocodingResult, WeatherData

class TestOpenWeatherMapClient:
    """Test suite for OpenWeatherMap client"""
    
    @pytest.fixture
    def mock_cache(self):
        """Mock cache for testing"""
        cache = Mock(spec=WeatherCacheInterface)
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock(return_value=True)
        cache.is_expired = AsyncMock(return_value=True)
        return cache
    
    @pytest.fixture
    def client(self, mock_cache):
        """Create client with mock cache"""
        return OpenWeatherMapClient(
            api_key="test_key",
            cache=mock_cache
        )
    
    async def test_get_coordinates_success(self, client, mock_cache):
        """Test successful geocoding"""
        # Mock API response
        # Verify cache check
        # Verify API call
        # Verify cache store
        # Verify result format
        pass
    
    async def test_get_coordinates_from_cache(self, client, mock_cache):
        """Test geocoding from cache"""
        # Mock cache hit
        # Verify no API call
        # Verify result
        pass
    
    async def test_get_weather_success(self, client, mock_cache):
        """Test successful weather fetch"""
        pass
    
    async def test_get_weather_from_cache(self, client, mock_cache):
        """Test weather from cache"""
        pass
    
    async def test_get_weather_by_city_success(self, client, mock_cache):
        """Test combined operation"""
        pass
    
    async def test_api_error_handling(self, client, mock_cache):
        """Test API error handling"""
        pass
    
    async def test_network_error_handling(self, client, mock_cache):
        """Test network error handling"""
        pass
    
    async def test_cache_expiration(self, client, mock_cache):
        """Test cache TTL logic"""
        pass

class TestDatabaseWeatherCache:
    """Test suite for database cache"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database wrapper"""
        pass
    
    @pytest.fixture
    def cache(self, mock_db):
        """Create cache with mock DB"""
        return DatabaseWeatherCache(mock_db)
    
    async def test_get_existing(self, cache, mock_db):
        """Test getting existing cache entry"""
        pass
    
    async def test_get_nonexistent(self, cache, mock_db):
        """Test getting non-existent entry"""
        pass
    
    async def test_set_new(self, cache, mock_db):
        """Test storing new entry"""
        pass
    
    async def test_set_update(self, cache, mock_db):
        """Test updating existing entry"""
        pass
    
    async def test_is_expired_true(self, cache, mock_db):
        """Test expired entry detection"""
        pass
    
    async def test_is_expired_false(self, cache, mock_db):
        """Test valid entry detection"""
        pass
```

### 6.2 Integration Tests

Create manual integration test script for real API testing:

```python
# lib/openweathermap/test_integration.py
async def test_real_api():
    """Manual test with real API (requires valid API key)"""
    # Test geocoding for known cities
    # Test weather for known coordinates
    # Test combined operation
    # Verify cache behavior
    pass
```

---

## 7. Usage Examples

### 7.1 Basic Usage

```python
from lib.openweathermap.client import OpenWeatherMapClient
from lib.openweathermap.database_cache import DatabaseWeatherCache
from internal.database.wrapper import DatabaseWrapper

# Initialize
db = DatabaseWrapper("gromozeka.db")
cache = DatabaseWeatherCache(db)

async with OpenWeatherMapClient(
    api_key="your_api_key",
    cache=cache
) as client:
    # Get coordinates
    location = await client.get_coordinates("Moscow", "RU")
    if location:
        print(f"Moscow: {location['lat']}, {location['lon']}")
        print(f"Russian name: {location['local_names'].get('ru', 'N/A')}")
    
    # Get weather
    weather = await client.get_weather(55.7558, 37.6173)
    if weather:
        print(f"Current temp: {weather['current']['temp']}°C")
        print(f"Description: {weather['current']['weather_description']}")
    
    # Combined operation
    result = await client.get_weather_by_city("London", "GB")
    if result:
        print(f"Location: {result['location']['name']}")
        print(f"Weather: {result['weather']['current']['temp']}°C")
```

### 7.2 Bot Integration Example

```python
# In bot handlers
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weather command"""
    # Parse city from command
    city = context.args[0] if context.args else "Moscow"
    
    # Get weather
    result = await self.weather_client.get_weather_by_city(city)
    
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

---

## 8. Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Create `lib/openweathermap/` directory structure
- [ ] Implement data models in `models.py`
- [ ] Implement cache interface in `cache_interface.py`
- [ ] Add database table to `DatabaseWrapper._create_tables()`
- [ ] Add `CacheDict` to `internal/database/models.py`
- [ ] Implement database cache methods in `DatabaseWrapper`
- [ ] Implement `DatabaseWeatherCache` class

### Phase 2: Client Implementation
- [ ] Implement `OpenWeatherMapClient.__init__()` and context manager
- [ ] Implement `_make_request()` helper method
- [ ] Implement `get_coordinates()` with caching
- [ ] Implement `get_weather()` with caching
- [ ] Implement `get_weather_by_city()` combined method
- [ ] Add error handling and logging throughout

### Phase 3: Configuration
- [ ] Add weather config section to `configs/00-defaults/config.toml`
- [ ] Add `get_weather_config()` to `ConfigManager`
- [ ] Update `__init__.py` exports

### Phase 4: Testing
- [ ] Write unit tests for `OpenWeatherMapClient`
- [ ] Write unit tests for `DatabaseWeatherCache`
- [ ] Write integration test script
- [ ] Test with real API (manual verification)
- [ ] Test cache behavior (TTL, expiration, updates)

### Phase 5: Documentation
- [ ] Add docstrings to all classes and methods
- [ ] Create usage examples in module docstring
- [ ] Update project README if needed
- [ ] Create task completion report

---

## 9. API Reference

### 9.1 OpenWeatherMap Geocoding API

**Endpoint:** `http://api.openweathermap.org/geo/1.0/direct`

**Parameters:**
- `q`: City name, state code (US only), country code (e.g., "London,GB")
- `limit`: Number of results (default 5, max 5)
- `appid`: API key

**Response Example:**
```json
[
  {
    "name": "Moscow",
    "local_names": {
      "ru": "Москва",
      "en": "Moscow"
    },
    "lat": 55.7558,
    "lon": 37.6173,
    "country": "RU"
  }
]
```

### 9.2 OpenWeatherMap One Call API 3.0

**Endpoint:** `https://api.openweathermap.org/data/3.0/onecall`

**Parameters:**
- `lat`: Latitude
- `lon`: Longitude
- `exclude`: Parts to exclude (comma-separated: "minutely,hourly,alerts")
- `appid`: API key
- `units`: Units (metric, imperial, standard)
- `lang`: Language code

**Response Example:**
```json
{
  "lat": 55.7558,
  "lon": 37.6173,
  "timezone": "Europe/Moscow",
  "current": {
    "dt": 1697644800,
    "temp": 15.5,
    "feels_like": 14.2,
    "pressure": 1013,
    "humidity": 65,
    "clouds": 40,
    "wind_speed": 3.5,
    "wind_deg": 180,
    "weather": [
      {
        "id": 802,
        "main": "Clouds",
        "description": "scattered clouds"
      }
    ]
  },
  "daily": [
    {
      "dt": 1697644800,
      "temp": {
        "day": 15.5,
        "min": 10.2,
        "max": 18.3
      },
      "pressure": 1013,
      "humidity": 65,
      "wind_speed": 3.5,
      "clouds": 40,
      "pop": 0.2,
      "weather": [
        {
          "id": 802,
          "main": "Clouds",
          "description": "scattered clouds"
        }
      ]
    }
  ]
}
```

---

## 10. Error Handling Strategy

### 10.1 API Errors

- **401 Unauthorized:** Invalid API key → Log error, return None
- **404 Not Found:** City not found → Log warning, return None
- **429 Too Many Requests:** Rate limit → Log error, return cached data if available
- **500+ Server Errors:** OpenWeatherMap issues → Log error, return cached data if available

### 10.2 Network Errors

- **Timeout:** Log error, return cached data if available
- **Connection Error:** Log error, return cached data if available
- **DNS Error:** Log error, return None

### 10.3 Cache Errors

- **Database Error:** Log error, continue without cache (direct API call)
- **JSON Parse Error:** Log error, invalidate cache entry

### 10.4 Logging Levels

- **DEBUG:** Cache hits/misses, API requests
- **INFO:** Successful operations
- **WARNING:** City not found, cache misses
- **ERROR:** API errors, network errors, database errors

---

## 11. Performance Considerations

### 11.1 Caching Strategy

- **Geocoding:** 30-day TTL (coordinates rarely change)
- **Weather:** 60-minute TTL (balance freshness vs API calls)
- **Cache key normalization:** Lowercase, trimmed, consistent format
- **Coordinate rounding:** 4 decimal places (~11m precision)

### 11.2 Database Optimization

- **Index on (cache_type, updated_at):** Fast expiration queries
- **Primary key on cache_key:** Fast lookups
- **Periodic cleanup:** Remove expired entries (can be scheduled task)

### 11.3 API Rate Limits

OpenWeatherMap free tier:
- 60 calls/minute
- 1,000,000 calls/month

Our caching strategy should keep us well within limits for typical bot usage.

---

## 12. Future Enhancements

### 12.1 Potential Features

- [ ] Weather alerts/warnings support
- [ ] Hourly forecast (currently excluded)
- [ ] Historical weather data
- [ ] Multiple language support for weather descriptions
- [ ] Weather icons/emoji mapping
- [ ] Air quality data (separate API)
- [ ] UV index tracking

### 12.2 Optimization Opportunities

- [ ] Batch geocoding for multiple cities
- [ ] Predictive cache warming (popular cities)
- [ ] Redis cache backend option
- [ ] Response compression
- [ ] Retry logic with exponential backoff

---

## 13. Dependencies

### 13.1 Required Packages

Already in project:
- `aiohttp` - Async HTTP