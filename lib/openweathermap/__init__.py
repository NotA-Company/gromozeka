"""
OpenWeatherMap Async Client Library

This module provides an async client for the OpenWeatherMap API with database-backed caching.
Supports geocoding (city name → coordinates) and weather data retrieval.

Example usage:
    from lib.openweathermap import OpenWeatherMapClient, DictWeatherCache

    # Initialize with simple dict cache
    cache = DictWeatherCache(default_ttl=3600)  # 1 hour TTL

    client = OpenWeatherMapClient(
        api_key="your_api_key",
        cache=cache
    )
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

from .client import OpenWeatherMapClient
from .models import CombinedWeatherResult, CurrentWeather, DailyWeather, GeocodingResult, WeatherData

__all__ = [
    "GeocodingResult",
    "CurrentWeather",
    "DailyWeather",
    "WeatherData",
    "CombinedWeatherResult",
    "OpenWeatherMapClient",
]
