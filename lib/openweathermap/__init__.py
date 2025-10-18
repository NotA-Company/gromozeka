"""
OpenWeatherMap Async Client Library

This module provides an async client for the OpenWeatherMap API with database-backed caching.
Supports geocoding (city name → coordinates) and weather data retrieval.

Example usage:
    from lib.openweathermap import OpenWeatherMapClient, DictWeatherCache
    
    # Initialize with simple dict cache
    cache = DictWeatherCache(default_ttl=3600)  # 1 hour TTL
    
    async with OpenWeatherMapClient(
        api_key="your_api_key",
        cache=cache
    ) as client:
        # Get weather by city
        result = await client.getWeatherByCity("Moscow", "RU")
        if result:
            print(f"Temperature: {result['weather']['current']['temp']}°C")
    
    # Or use database cache for persistence:
    # from internal.database.openweathermap_cache import DatabaseWeatherCache
    # from internal.database.wrapper import DatabaseWrapper
    # db = DatabaseWrapper("gromozeka.db")
    # cache = DatabaseWeatherCache(db)
"""

from .models import (
    GeocodingResult,
    CurrentWeather,
    DailyWeather,
    WeatherData,
    CombinedWeatherResult,
    CacheDict
)

from .cache_interface import WeatherCacheInterface
from .dict_cache import DictWeatherCache
from .client import OpenWeatherMapClient

__all__ = [
    'GeocodingResult',
    'CurrentWeather',
    'DailyWeather',
    'WeatherData',
    'CombinedWeatherResult',
    'CacheDict',
    'WeatherCacheInterface',
    'DictWeatherCache',
    'OpenWeatherMapClient'
]