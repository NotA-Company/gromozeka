"""
Abstract cache interface for weather data caching

This module defines the abstract interface that all weather cache implementations
must follow. Similar to the pattern used in lib/spam/storage_interface.py.
"""

from abc import ABC, abstractmethod
from typing import Optional

from .models import GeocodingResult, WeatherData

class WeatherCacheInterface(ABC):
    """Abstract interface for weather data caching"""

    @abstractmethod
    async def getWeather(self, key: str, ttl: Optional[int] = None) -> Optional[WeatherData]:
        """
        Get cached Weather data by key
        
        Args:
            key: <lat>,<lon> (e.g., "55.7558,37.6173")
            
        Returns:
            JSON string if found and not expired, None otherwise
        """
        pass
    
    @abstractmethod
    async def setWeather(self, key: str, data: WeatherData) -> bool:
        """
        Store Weather data in cache
        
        Args:
            key: Cache key
            data: JSON string to store
            
        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def getGeocoging(self, key: str, ttl: Optional[int] = None) -> Optional[GeocodingResult]:
        """
        Get cached Geocoging data by key
        
        Args:
            key: <lat>,<lon> (e.g., "Moscow,RU")
            
        Returns:
            JSON string if found and not expired, None otherwise
        """
        pass
    
    @abstractmethod
    async def setGeocoging(self, key: str, data: GeocodingResult) -> bool:
        """
        Store Geocoging data in cache
        
        Args:
            key: Cache key
            data: JSON string to store
            
        Returns:
            True if successful, False otherwise
        """
        pass