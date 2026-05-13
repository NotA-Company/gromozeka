"""OpenWeatherMap Async Client.

This module provides the main OpenWeatherMapClient class for interacting with
the OpenWeatherMap API with database-backed caching support. The client supports
geocoding (converting city names to coordinates) and weather data retrieval
(current conditions and daily forecasts) with configurable caching and rate limiting.

Example:
    >>> from lib.openweathermap import OpenWeatherMapClient
    >>> from lib.cache import NullCache
    >>>
    >>> client = OpenWeatherMapClient(
    ...     apiKey="your_api_key",
    ...     weatherCache=NullCache(),
    ...     geocodingCache=NullCache()
    ... )
    >>>
    >>> # Get weather by city
    >>> result = await client.getWeatherByCity("Moscow", "RU")
    >>> if result:
    ...     print(f"Temperature: {result['weather']['current']['temp']}°C")
"""

import json
import logging
from typing import List, Optional

import httpx

from lib.cache import CacheInterface, NullCache
from lib.rate_limiter import RateLimiterManager

from .models import CombinedWeatherResult, CurrentWeather, DailyWeather, GeocodingResult, WeatherData

logger = logging.getLogger(__name__)


class OpenWeatherMapClient:
    """Async client for OpenWeatherMap API with caching and rate limiting.

    This client provides methods to:
    - Convert city names to geographic coordinates (geocoding)
    - Retrieve current weather conditions and daily forecasts
    - Cache results to reduce API calls
    - Apply rate limiting to respect API quotas

    The client creates a new HTTP session for each request to support proper
    concurrent requests without connection reuse issues.

    Attributes:
        GEOCODING_API: URL endpoint for geocoding API.
        WEATHER_API: URL endpoint for weather data API.
        apiKey: OpenWeatherMap API authentication key.
        weatherCache: Cache instance for weather data storage.
        geocodingCache: Cache instance for geocoding results storage.
        geocodingTTL: Time-to-live for geocoding cache entries in seconds.
        weatherTTL: Time-to-live for weather cache entries in seconds.
        requestTimeout: HTTP request timeout in seconds.
        defaultLanguage: Default language code for weather descriptions.
        rateLimiterQueue: Name of the rate limiter queue to use.
        _rateLimiter: Rate limiter manager instance.

    Example:
        >>> from lib.openweathermap import OpenWeatherMapClient
        >>> from lib.cache import NullCache
        >>>
        >>> client = OpenWeatherMapClient(
        ...     apiKey="your_api_key",
        ...     weatherCache=NullCache(),
        ...     geocodingCache=NullCache(),
        ...     geocodingTTL=2592000,  # 30 days
        ...     weatherTTL=1800        # 30 minutes
        ... )
        >>>
        >>> # Get coordinates
        >>> location = await client.getCoordinates("Moscow", "RU")
        >>>
        >>> # Get weather
        >>> weather = await client.getWeather(55.7558, 37.6173)
        >>>
        >>> # Combined operation
        >>> result = await client.getWeatherByCity("Moscow", "RU")
    """

    GEOCODING_API: str = "http://api.openweathermap.org/geo/1.0/direct"
    WEATHER_API: str = "https://api.openweathermap.org/data/3.0/onecall"

    def __init__(
        self,
        apiKey: str,
        weatherCache: Optional[CacheInterface[str, WeatherData]] = None,
        geocodingCache: Optional[CacheInterface[str, GeocodingResult]] = None,
        geocodingTTL: Optional[int] = 2592000,  # 30 days
        weatherTTL: Optional[int] = 1800,  # 30 minutes
        requestTimeout: int = 10,
        defaultLanguage: str = "ru",
        rateLimiterQueue: str = "openweathermap",
    ) -> None:
        """Initialize OpenWeatherMap client.

        Args:
            apiKey: OpenWeatherMap API authentication key.
            weatherCache: Cache instance for storing weather data. If None,
                uses NullCache (no caching).
            geocodingCache: Cache instance for storing geocoding results. If None,
                uses NullCache (no caching).
            geocodingTTL: Time-to-live for geocoding cache entries in seconds.
                Defaults to 2592000 (30 days).
            weatherTTL: Time-to-live for weather cache entries in seconds.
                Defaults to 1800 (30 minutes).
            requestTimeout: HTTP request timeout in seconds. Defaults to 10.
            defaultLanguage: Default language code for weather descriptions and
                location names. Defaults to "ru" (Russian).
            rateLimiterQueue: Name of the rate limiter queue to use for API
                request throttling. Defaults to "openweathermap".
        """
        self.apiKey = apiKey
        self.weatherCache: CacheInterface[str, WeatherData] = (
            weatherCache if weatherCache is not None else NullCache[str, WeatherData]()
        )
        self.geocodingCache: CacheInterface[str, GeocodingResult] = (
            geocodingCache if geocodingCache is not None else NullCache[str, GeocodingResult]()
        )
        self.geocodingTTL = geocodingTTL
        self.weatherTTL = weatherTTL
        self.requestTimeout = requestTimeout
        self.defaultLanguage = defaultLanguage
        self.rateLimiterQueue = rateLimiterQueue
        self._rateLimiter = RateLimiterManager.getInstance()

    async def getCoordinates(
        self, city: str, country: Optional[str] = None, state: Optional[str] = None, limit: int = 1
    ) -> Optional[GeocodingResult]:
        """Get geographic coordinates for a city name.

        Uses the OpenWeatherMap Geocoding API to convert city names to
        latitude/longitude coordinates. Results are cached to reduce API calls.

        API endpoint: http://api.openweathermap.org/geo/1.0/direct

        Args:
            city: City name (e.g., "Moscow", "London").
            country: Optional ISO 3166 country code (e.g., "RU", "GB", "US").
            state: Optional state or province code (primarily for US cities).
            limit: Maximum number of results to return. Defaults to 1.
                Only the first result is returned.

        Returns:
            GeocodingResult dictionary containing:
                - name: City name
                - local_names: Dictionary of localized city names
                - lat: Latitude coordinate
                - lon: Longitude coordinate
                - country: Country code
                - state: State or province code
            Returns None if the location is not found.

        Raises:
            Exception: Cache errors are caught and logged, but do not prevent
                the API request from being made.

        Note:
            Cache key format: "city,country,state" (normalized: city lowercase,
            country uppercase, state lowercase).
        """
        # Build cache key
        cacheKeyParts: List[str] = [city.lower().strip()]
        if country:
            cacheKeyParts.append(country.upper().strip())
        if state:
            cacheKeyParts.append(state.lower().strip())
        cacheKey: str = ",".join(cacheKeyParts)

        # Check cache first
        try:
            cachedData: Optional[GeocodingResult] = await self.geocodingCache.get(cacheKey, self.geocodingTTL)
            if cachedData:
                logger.debug(f"Cache hit for geocoding: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for geocoding {cacheKey}: {e}")

        # Build query string
        queryParts: List[str] = [city]
        if state:
            queryParts.append(state)
        if country:
            queryParts.append(country)
        query: str = ",".join(queryParts)

        # Make API request
        params: dict = {"q": query, "limit": limit, "appid": self.apiKey}

        responseData: Optional[dict] = await self._makeRequest(self.GEOCODING_API, params)
        if not responseData or not isinstance(responseData, list) or len(responseData) == 0:
            logger.warning(f"No geocoding results for: {query}")
            return None

        # Extract first result and convert to our format
        apiResult: dict = responseData[0]
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
            await self.geocodingCache.set(cacheKey, result)
            logger.debug(f"Cached geocoding result: {cacheKey}")
        except Exception as e:
            logger.warning(f"Failed to cache geocoding result {cacheKey}: {e}")

        return result

    async def getWeather(self, lat: float, lon: float, exclude: Optional[List[str]] = None) -> Optional[WeatherData]:
        """Get weather data by geographic coordinates.

        Retrieves current weather conditions and daily forecasts from the
        OpenWeatherMap One Call API. Results are cached to reduce API calls.

        API endpoint: https://api.openweathermap.org/data/3.0/onecall

        Args:
            lat: Latitude coordinate in decimal degrees.
            lon: Longitude coordinate in decimal degrees.
            exclude: Optional list of data blocks to exclude from the response.
                Valid values: "current", "minutely", "hourly", "daily", "alerts".
                Defaults to ["minutely", "hourly", "alerts"] to reduce response size.

        Returns:
            WeatherData dictionary containing:
                - lat: Latitude coordinate
                - lon: Longitude coordinate
                - timezone: Timezone name
                - timezone_offset: UTC offset in seconds
                - current: CurrentWeather dictionary with current conditions
                - daily: List of DailyWeather dictionaries (up to 8 days)
            Returns None if the API request fails or no data is available.

        Raises:
            Exception: Cache errors are caught and logged, but do not prevent
                the API request from being made.

        Note:
            Cache key format: "lat,lon" (coordinates rounded to 4 decimal places).
            Weather data is returned in metric units (Celsius, m/s, etc.).
        """
        # Round coordinates to 4 decimal places for cache key
        latRounded: float = round(lat, 4)
        lonRounded: float = round(lon, 4)
        cacheKey: str = f"{latRounded},{lonRounded}"

        # Check cache first
        try:
            cachedData: Optional[WeatherData] = await self.weatherCache.get(cacheKey, self.weatherTTL)
            if cachedData:
                logger.debug(f"Cache hit for weather: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for weather {cacheKey}: {e}")

        # Default exclusions
        if exclude is None:
            exclude = ["minutely", "hourly", "alerts"]

        # Make API request
        params: dict = {
            "lat": lat,
            "lon": lon,
            "exclude": ",".join(exclude),
            "units": "metric",
            "lang": self.defaultLanguage,
            "appid": self.apiKey,
        }

        responseData: Optional[dict] = await self._makeRequest(self.WEATHER_API, params)
        if not responseData:
            logger.warning(f"No weather data for: {lat}, {lon}")
            return None

        # Extract and convert to our format
        currentData: dict = responseData.get("current", {})
        weather_list: List[dict] = currentData.get("weather", [])
        weather_info: dict = weather_list[0] if weather_list else {}

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
        dailyForecasts: List[DailyWeather] = []
        for dailyItem in responseData.get("daily", [])[:8]:  # Max 8 days
            dailyWeatherInfo: dict = dailyItem.get("weather", [{}])[0]
            tempData: dict = dailyItem.get("temp", {})
            feelsLikeData: dict = dailyItem.get("feels_like", {})

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
            await self.weatherCache.set(cacheKey, result)
            logger.debug(f"Cached weather result: {cacheKey}")
        except Exception as e:
            logger.warning(f"Failed to cache weather result {cacheKey}: {e}")

        return result

    async def getWeatherByCity(
        self, city: str, country: Optional[str] = None, state: Optional[str] = None
    ) -> Optional[CombinedWeatherResult]:
        """Get weather data for a city by name.

        This is a convenience method that combines geocoding and weather retrieval
        into a single operation. It first calls getCoordinates() to resolve the
        city name to coordinates, then calls getWeather() to retrieve the weather
        data. Both operations use their respective caches.

        Args:
            city: City name (e.g., "Moscow", "London").
            country: Optional ISO 3166 country code (e.g., "RU", "GB", "US").
            state: Optional state or province code (primarily for US cities).

        Returns:
            CombinedWeatherResult dictionary containing:
                - location: GeocodingResult with city information and coordinates
                - weather: WeatherData with current conditions and daily forecast
            Returns None if geocoding fails (city not found) or weather retrieval fails.

        Example:
            >>> result = await client.getWeatherByCity("Moscow", "RU")
            >>> if result:
            ...     print(f"City: {result['location']['name']}")
            ...     print(f"Temp: {result['weather']['current']['temp']}°C")
        """
        # Get coordinates first
        location: Optional[GeocodingResult] = await self.getCoordinates(city, country, state)
        if not location:
            logger.warning(f"Failed to get coordinates for: {city}, {country}")
            return None

        # Get weather for those coordinates
        weather: Optional[WeatherData] = await self.getWeather(location["lat"], location["lon"])
        if not weather:
            logger.warning(f"Failed to get weather for: {location['lat']}, {location['lon']}")
            return None

        result: CombinedWeatherResult = {
            "location": location,
            "weather": weather,
        }

        return result

    async def _makeRequest(self, url: str, params: dict) -> Optional[dict]:
        """Make HTTP request to OpenWeatherMap API.

        Creates a new HTTP session for each request to support proper concurrent
        requests without connection reuse issues. Applies rate limiting before
        making the request.

        Args:
            url: API endpoint URL (e.g., geocoding or weather API endpoint).
            params: Query parameters dictionary. The API key is included in params
                by the caller.

        Returns:
            Parsed JSON response as a dictionary, or None if the request fails.
            Returns None for the following error conditions:
                - HTTP 401: Invalid API key
                - HTTP 404: Location not found
                - HTTP 429: Rate limit exceeded
                - Other HTTP errors
                - Network timeout
                - Network connection errors
                - JSON parsing errors
                - Unexpected exceptions

        Raises:
            httpx.TimeoutException: Request timeout (caught and logged).
            httpx.RequestError: Network connection errors (caught and logged).
            json.JSONDecodeError: JSON parsing errors (caught and logged).
            Exception: Unexpected errors (caught and logged).

        Note:
            All exceptions are caught and logged, returning None instead of
            propagating errors to allow graceful degradation.
        """
        try:
            logger.debug(f"Making request to {url} with params: {params}")
            await self._rateLimiter.applyLimit(self.rateLimiterQueue)

            # Create new session for each request
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
                response: httpx.Response = await session.get(url, params=params)
                if response.status_code == 200:
                    data: dict = response.json()
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
