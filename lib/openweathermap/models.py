"""
Data models for OpenWeatherMap API client

This module defines TypedDict classes for API responses and cache entries.
All models follow the OpenWeatherMap API v3.0 specification.
"""

from typing import Dict, Optional, TypedDict, List
from dataclasses import dataclass
import datetime

# API Response Models

class GeocodingResult(TypedDict):
    """Result from geocoding API"""
    name: str                   # City name (English)
    local_names: Dict[str,str]  # Names in different languages {"ru": "Москва", "en": "Moscow"}
    lat: float                  # Latitude
    lon: float                  # Longitude
    country: str                # Country code (e.g., "RU")
    state: Optional[str]        # State/region name (if available)

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
    daily: List[DailyWeather]  # Up to 8 days

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