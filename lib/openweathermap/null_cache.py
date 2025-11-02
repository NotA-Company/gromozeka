"""
Null cache implementation for OpenWeatherMap client

This module provides a null cache implementation that implements the
WeatherCacheInterface but doesn't actually cache anything. Useful for testing
scenarios where caching is not needed.
"""

from typing import Optional

from .cache_interface import WeatherCacheInterface
from .models import GeocodingResult, WeatherData


class NullWeatherCache(WeatherCacheInterface):
    """Null cache implementation that doesn't actually cache anything"""

    async def getWeather(self, key: str, ttl: Optional[int] = None) -> Optional[WeatherData]:
        """
        Always return None (no cached data)

        Args:
            key: Cache key
            ttl: TTL in seconds (ignored)

        Returns:
            None (never found in cache)
        """
        return None

    async def setWeather(self, key: str, data: WeatherData) -> bool:
        """
        Do nothing (don't cache)

        Args:
            key: Cache key
            data: WeatherData to store

        Returns:
            True (always successful, even though nothing was stored)
        """
        return True

    async def getGeocoging(self, key: str, ttl: Optional[int] = None) -> Optional[GeocodingResult]:
        """
        Always return None (no cached data)

        Args:
            key: Cache key
            ttl: TTL in seconds (ignored)

        Returns:
            None (never found in cache)
        """
        return None

    async def setGeocoging(self, key: str, data: GeocodingResult) -> bool:
        """
        Do nothing (don't cache)

        Args:
            key: Cache key
            data: GeocodingResult to store

        Returns:
            True (always successful, even though nothing was stored)
        """
        return True
