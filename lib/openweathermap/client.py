"""
OpenWeatherMap Async Client

This module provides the main OpenWeatherMapClient class for interacting with
the OpenWeatherMap API with database-backed caching support.
"""

import json
import logging
from typing import List, Optional

import httpx

from .cache_interface import WeatherCacheInterface
from .models import CombinedWeatherResult, CurrentWeather, DailyWeather, GeocodingResult, WeatherData

logger = logging.getLogger(__name__)


class OpenWeatherMapClient:
    """
    Async client for OpenWeatherMap API with caching

    Creates a new HTTP session for each request to support proper concurrent requests.

    Example usage:
        cache = DatabaseWeatherCache(db_wrapper)
        client = OpenWeatherMapClient(
            api_key="your_key",
            cache=cache,
            geocoding_ttl=2592000,  # 30 days
            weather_ttl=1800         # 30 minutes
        )

        # Get coordinates
        location = await client.getCoordinates("Moscow", "RU")

        # Get weather
        weather = await client.getWeather(55.7558, 37.6173)

        # Combined operation
        result = await client.getWeatherByCity("Moscow", "RU")
    """

    GEOCODING_API = "http://api.openweathermap.org/geo/1.0/direct"
    WEATHER_API = "https://api.openweathermap.org/data/3.0/onecall"

    def __init__(
        self,
        apiKey: str,
        cache: WeatherCacheInterface,
        geocodingTTL: Optional[int] = 2592000,  # 30 days
        weatherTTL: Optional[int] = 1800,  # 30 minutes
        requestTimeout: int = 10,
        defaultLanguage: str = "ru",
    ):
        """
        Initialize OpenWeatherMap client

        Args:
            apiKey: OpenWeatherMap API key
            cache: Cache implementation (must implement WeatherCacheInterface)
            geocodingTTL: Cache TTL for geocoding results (seconds)
            weatherTTL: Cache TTL for weather data (seconds)
            requestTimeout: HTTP request timeout (seconds)
            defaultLanguage: Default language for location names
        """
        self.apiKey = apiKey
        self.cache = cache
        self.geocodingTTL = geocodingTTL
        self.weatherTTL = weatherTTL
        self.requestTimeout = requestTimeout
        self.defaultLanguage = defaultLanguage
        # No persistent session - create new session for each request

    async def getCoordinates(
        self, city: str, country: Optional[str] = None, state: Optional[str] = None, limit: int = 1
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
        # Build cache key
        cacheKeyParts = [city.lower().strip()]
        if country:
            cacheKeyParts.append(country.upper().strip())
        if state:
            cacheKeyParts.append(state.lower().strip())
        cacheKey = ",".join(cacheKeyParts)

        # Check cache first
        try:
            cachedData = await self.cache.getGeocoging(cacheKey, self.geocodingTTL)
            if cachedData:
                logger.debug(f"Cache hit for geocoding: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for geocoding {cacheKey}: {e}")

        # Build query string
        queryParts = [city]
        if state:
            queryParts.append(state)
        if country:
            queryParts.append(country)
        query = ",".join(queryParts)

        # Make API request
        params = {"q": query, "limit": limit, "appid": self.apiKey}

        responseData = await self._makeRequest(self.GEOCODING_API, params)
        if not responseData or not isinstance(responseData, list) or len(responseData) == 0:
            logger.warning(f"No geocoding results for: {query}")
            return None

        # Extract first result and convert to our format
        apiResult = responseData[0]
        result: GeocodingResult = {
            "name": apiResult.get("name", ""),
            "local_names": apiResult.get("local_names", {}),
            "lat": float(apiResult.get("lat", 0)),
            "lon": float(apiResult.get("lon", 0)),
            "country": apiResult.get("country", ""),
            "state": apiResult.get("state", ""),
        }

        # Store in cache
        try:
            await self.cache.setGeocoging(cacheKey, result)
            logger.debug(f"Cached geocoding result: {cacheKey}")
        except Exception as e:
            logger.warning(f"Failed to cache geocoding result {cacheKey}: {e}")

        return result

    async def getWeather(self, lat: float, lon: float, exclude: Optional[List[str]] = None) -> Optional[WeatherData]:
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
        # Round coordinates to 4 decimal places for cache key
        latRounded = round(lat, 4)
        lonRounded = round(lon, 4)
        cacheKey = f"{latRounded},{lonRounded}"

        # Check cache first
        try:
            cachedData = await self.cache.getWeather(cacheKey, self.weatherTTL)
            if cachedData:
                logger.debug(f"Cache hit for weather: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for weather {cacheKey}: {e}")

        # Default exclusions
        if exclude is None:
            exclude = ["minutely", "hourly", "alerts"]

        # Make API request
        params = {
            "lat": lat,
            "lon": lon,
            "exclude": ",".join(exclude),
            "units": "metric",
            "lang": self.defaultLanguage,
            "appid": self.apiKey,
        }

        responseData = await self._makeRequest(self.WEATHER_API, params)
        if not responseData:
            logger.warning(f"No weather data for: {lat}, {lon}")
            return None

        # Extract and convert to our format
        currentData = responseData.get("current", {})
        weather_list = currentData.get("weather", [])
        weather_info = weather_list[0] if weather_list else {}

        currentWeather: CurrentWeather = {
            "dt": currentData.get("dt", 0),
            "temp": float(currentData.get("temp", 0)),
            "feels_like": float(currentData.get("feels_like", 0)),
            "pressure": int(currentData.get("pressure", 0)),
            "humidity": int(currentData.get("humidity", 0)),
            "clouds": int(currentData.get("clouds", 0)),
            "dew_point": float(currentData.get("clouds", 0)),
            "uvi": float(currentData.get("uvi", 0)),
            "visibility": int(currentData.get("visibility", 0)),
            "sunrise": int(currentData.get("sunrise", 0)),
            "sunset": int(currentData.get("sunset", 0)),
            "wind_speed": float(currentData.get("wind_speed", 0)),
            "wind_deg": int(currentData.get("wind_deg", 0)),
            "wind_gust": currentData.get("wind_gust", None),
            "weather_id": int(weather_info.get("id", 0)),
            "weather_main": weather_info.get("main", ""),
            "weather_description": weather_info.get("description", ""),
        }

        # Process daily forecast
        dailyForecasts = []
        for dailyItem in responseData.get("daily", [])[:8]:  # Max 8 days
            dailyWeatherInfo = dailyItem.get("weather", [{}])[0]
            tempData = dailyItem.get("temp", {})
            feelsLikeData = dailyItem.get("feels_like", {})

            dailyWeather: DailyWeather = {
                "dt": dailyItem.get("dt", 0),
                "temp_day": float(tempData.get("day", 0)),
                "temp_night": float(tempData.get("night", 0)),
                "temp_eve": float(tempData.get("eve", 0)),
                "temp_morn": float(tempData.get("morn", 0)),
                "temp_min": float(tempData.get("min", 0)),
                "temp_max": float(tempData.get("max", 0)),
                "feels_like_day": float(feelsLikeData.get("day", 0)),
                "feels_like_night": float(feelsLikeData.get("night", 0)),
                "feels_like_morn": float(feelsLikeData.get("morn", 0)),
                "feels_like_eve": float(feelsLikeData.get("eve", 0)),
                "pressure": int(dailyItem.get("pressure", 0)),
                "humidity": int(dailyItem.get("humidity", 0)),
                "dew_point": float(dailyItem.get("dew_point", 0)),
                "clouds": int(dailyItem.get("clouds", 0)),
                "uvi": float(dailyItem.get("uvi", 0)),
                "wind_speed": float(dailyItem.get("wind_speed", 0)),
                "wind_deg": int(dailyItem.get("wind_deg", 0)),
                "wind_gust": dailyItem.get("wind_gust", None),
                "sunrise": int(dailyItem.get("sunrise", 0)),
                "sunset": int(dailyItem.get("sunset", 0)),
                "moonrise": int(dailyItem.get("moonrise", 0)),
                "moonset": int(dailyItem.get("moonset", 0)),
                "moon_phase": float(dailyItem.get("moon_phase", 0)),
                "pop": float(dailyItem.get("pop", 0)),
                "summary": dailyItem.get("summary", ""),
                "weather_id": int(dailyWeatherInfo.get("id", 0)),
                "weather_main": dailyWeatherInfo.get("main", ""),
                "weather_description": dailyWeatherInfo.get("description", ""),
            }
            dailyForecasts.append(dailyWeather)

        result: WeatherData = {
            "lat": float(responseData.get("lat", lat)),
            "lon": float(responseData.get("lon", lon)),
            "timezone": responseData.get("timezone", ""),
            "timezone_offset": responseData.get("timezone_offset", 0),
            "current": currentWeather,
            "daily": dailyForecasts,
        }

        # Store in cache
        try:
            await self.cache.setWeather(cacheKey, result)
            logger.debug(f"Cached weather result: {cacheKey}")
        except Exception as e:
            logger.warning(f"Failed to cache weather result {cacheKey}: {e}")

        return result

    async def getWeatherByCity(
        self, city: str, country: Optional[str] = None, state: Optional[str] = None
    ) -> Optional[CombinedWeatherResult]:
        """
        Combined operation: get coordinates then get weather

        This is a convenience method that calls getCoordinates()
        followed by getWeather(). Both operations use their
        respective caches.

        Args:
            city: City name
            country: Optional country code
            state: Optional state code

        Returns:
            CombinedWeatherResult with location and weather data,
            or None if geocoding fails
        """
        # Get coordinates first
        location = await self.getCoordinates(city, country, state)
        if not location:
            logger.warning(f"Failed to get coordinates for: {city}, {country}")
            return None

        # Get weather for those coordinates
        weather = await self.getWeather(location["lat"], location["lon"])
        if not weather:
            logger.warning(f"Failed to get weather for: {location['lat']}, {location['lon']}")
            return None

        result: CombinedWeatherResult = {
            "location": location,
            "weather": weather,
        }

        return result

    async def _makeRequest(self, url: str, params: dict) -> Optional[dict]:
        """
        Make HTTP request to OpenWeatherMap API

        Creates a new session for each request to support proper concurrent requests.

        Args:
            url: API endpoint URL
            params: Query parameters (api_key will be added automatically)

        Returns:
            Parsed JSON response or None on error
        """
        try:
            logger.debug(f"Making request to {url} with params: {params}")

            # Create new session for each request
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
                response = await session.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"API request successful: {response.status_code}")
                    logger.debug(f"API response: {data}")
                    return data
                elif response.status_code == 401:
                    logger.error("Invalid API key")
                    return None
                elif response.status_code == 404:
                    logger.warning("Location not found")
                    return None
                elif response.status_code == 429:
                    logger.error("Rate limit exceeded")
                    return None
                else:
                    logger.error(f"API request failed: {response.status_code}")
                    return None

        except httpx.TimeoutException:
            logger.error("Request timeout")
            return None
        except httpx.RequestError as e:
            logger.error(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during API request: {e}")
            return None
