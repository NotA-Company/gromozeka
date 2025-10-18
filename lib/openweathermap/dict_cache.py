"""
Simple dictionary-based weather cache implementation

This module provides a basic in-memory cache implementation using Python dictionaries.
Useful for testing and simple scenarios where persistent caching is not required.
"""

import time
import logging
from typing import Dict, Optional, Tuple

from .models import GeocodingResult, WeatherData
from .cache_interface import WeatherCacheInterface


class DictWeatherCache(WeatherCacheInterface):
    """Simple dictionary-based weather cache implementation"""

    def __init__(self, default_ttl: int = 3600):
        """
        Initialize cache with empty dictionaries

        Args:
            default_ttl: Default TTL in seconds (default: 1 hour)
        """
        self.weather_cache: Dict[str, Tuple[WeatherData, float]] = {}
        self.geocoding_cache: Dict[str, Tuple[GeocodingResult, float]] = {}
        self.default_ttl = default_ttl
        self.logger = logging.getLogger(__name__)

    def _is_expired(self, timestamp: float, ttl: Optional[int] = None) -> bool:
        """Check if cache entry is expired"""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        return time.time() - timestamp > effective_ttl

    def _cleanup_expired(self) -> None:
        """Remove expired entries from both caches"""
        # Clean weather cache
        expired_weather_keys = [
            key for key, (_, timestamp) in self.weather_cache.items()
            if self._is_expired(timestamp)
        ]
        for key in expired_weather_keys:
            del self.weather_cache[key]

        # Clean geocoding cache
        expired_geocoding_keys = [
            key for key, (_, timestamp) in self.geocoding_cache.items()
            if self._is_expired(timestamp)
        ]
        for key in expired_geocoding_keys:
            del self.geocoding_cache[key]

        if expired_weather_keys or expired_geocoding_keys:
            expired_count = len(expired_weather_keys) + len(expired_geocoding_keys)
            self.logger.debug(f"Cleaned up {expired_count} expired entries")

    async def getWeather(self, key: str, ttl: Optional[int] = None) -> Optional[WeatherData]:
        """
        Get cached Weather data by key

        Args:
            key: <lat>,<lon> (e.g., "55.7558,37.6173")
            ttl: TTL in seconds (uses default_ttl if None)

        Returns:
            WeatherData if found and not expired, None otherwise
        """
        try:
            self._cleanup_expired()

            if key in self.weather_cache:
                data, timestamp = self.weather_cache[key]
                if not self._is_expired(timestamp, ttl):
                    self.logger.debug(f"Cache hit for weather key: {key}")
                    return data
                else:
                    # Remove expired entry
                    del self.weather_cache[key]
                    self.logger.debug(f"Removed expired weather entry: {key}")

            self.logger.debug(f"Cache miss for weather key: {key}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get weather cache entry {key}: {e}")
            return None

    async def setWeather(self, key: str, data: WeatherData) -> bool:
        """
        Store Weather data in cache

        Args:
            key: Cache key
            data: WeatherData to store

        Returns:
            True if successful, False otherwise
        """
        try:
            self.weather_cache[key] = (data, time.time())
            self.logger.debug(f"Stored weather data for key: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to set weather cache entry {key}: {e}")
            return False

    async def getGeocoging(self, key: str, ttl: Optional[int] = None) -> Optional[GeocodingResult]:
        """
        Get cached Geocoding data by key

        Args:
            key: City name (e.g., "Moscow,RU")
            ttl: TTL in seconds (uses default_ttl if None)

        Returns:
            GeocodingResult if found and not expired, None otherwise
        """
        try:
            self._cleanup_expired()

            if key in self.geocoding_cache:
                data, timestamp = self.geocoding_cache[key]
                if not self._is_expired(timestamp, ttl):
                    self.logger.debug(f"Cache hit for geocoding key: {key}")
                    return data
                else:
                    # Remove expired entry
                    del self.geocoding_cache[key]
                    self.logger.debug(f"Removed expired geocoding entry: {key}")

            self.logger.debug(f"Cache miss for geocoding key: {key}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get geocoding cache entry {key}: {e}")
            return None

    async def setGeocoging(self, key: str, data: GeocodingResult) -> bool:
        """
        Store Geocoding data in cache

        Args:
            key: Cache key
            data: GeocodingResult to store

        Returns:
            True if successful, False otherwise
        """
        try:
            self.geocoding_cache[key] = (data, time.time())
            self.logger.debug(f"Stored geocoding data for key: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to set geocoding cache entry {key}: {e}")
            return False

    def clear(self) -> None:
        """Clear all cached data"""
        self.weather_cache.clear()
        self.geocoding_cache.clear()
        self.logger.debug("Cleared all cache data")

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        self._cleanup_expired()
        return {
            "weather_entries": len(self.weather_cache),
            "geocoding_entries": len(self.geocoding_cache),
            "total_entries": len(self.weather_cache) + len(self.geocoding_cache)
        }
