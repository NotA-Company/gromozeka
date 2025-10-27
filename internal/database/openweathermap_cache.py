"""
Database-backed weather cache implementation

This module provides a concrete implementation of the WeatherCacheInterface
using the project's DatabaseWrapper for persistent caching.
"""

import json
import logging
from typing import Optional

import lib.utils as utils
from lib.openweathermap.cache_interface import WeatherCacheInterface
from lib.openweathermap.models import GeocodingResult, WeatherData

from .models import CacheType
from .wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class DatabaseWeatherCache(WeatherCacheInterface):
    """Database-backed weather cache implementation"""

    def __init__(self, db: DatabaseWrapper):
        """
        Initialize cache with database wrapper

        Args:
            db_wrapper: DatabaseWrapper instance from internal.database.wrapper
        """
        self.db = db

    async def getWeather(self, key: str, ttl: Optional[int] = None) -> Optional[WeatherData]:
        """Get cached data if exists and not expired"""
        try:
            # logger.debug(f"Getting WEATHER cache entry {key}, ttl={ttl}")
            cacheEntry = self.db.getCacheEntry(key, cacheType=CacheType.WEATHER, ttl=ttl)
            if cacheEntry:
                return json.loads(cacheEntry["data"])  # TODO: Add validation
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    async def setWeather(self, key: str, data: WeatherData) -> bool:
        """Store data in cache"""
        try:
            return self.db.setCacheEntry(key, data=utils.jsonDumps(data), cacheType=CacheType.WEATHER)
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    async def getGeocoging(self, key: str, ttl: Optional[int] = None) -> Optional[GeocodingResult]:
        """Get cached data if exists and not expired"""
        try:
            cacheEntry = self.db.getCacheEntry(key, cacheType=CacheType.GEOCODING, ttl=ttl)
            if cacheEntry:
                return json.loads(cacheEntry["data"])  # TODO: Add validation
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    async def setGeocoging(self, key: str, data: GeocodingResult) -> bool:
        """Store data in cache"""
        try:
            return self.db.setCacheEntry(key, data=utils.jsonDumps(data), cacheType=CacheType.GEOCODING)
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False
