"""Data models for OpenWeatherMap API client.

This module defines TypedDict classes for API responses and cache entries.
All models follow the OpenWeatherMap API v3.0 specification.

The models provide type-safe structures for:
- Geocoding results from location search
- Current weather conditions
- Daily weather forecasts
- Complete weather data responses
- Combined location and weather results

Example:
    >>> from lib.openweathermap.models import GeocodingResult, WeatherData
    >>> location: GeocodingResult = {
    ...     "name": "Moscow",
    ...     "local_names": {"ru": "Москва", "en": "Moscow"},
    ...     "lat": 55.7558,
    ...     "lon": 37.6173,
    ...     "country": "RU",
    ...     "state": None
    ... }
"""

from typing import Dict, List, Optional, TypedDict


class GeocodingResult(TypedDict):
    """Result from geocoding API.

    Represents a location found through the OpenWeatherMap geocoding API,
    containing coordinates and location metadata.

    Attributes:
        name: City name in English.
        local_names: Dictionary mapping language codes to localized city names.
            Example: {"ru": "Москва", "en": "Moscow", "de": "Moskau"}.
        lat: Latitude coordinate in decimal degrees.
        lon: Longitude coordinate in decimal degrees.
        country: ISO 3166-1 alpha-2 country code (e.g., "RU", "US", "GB").
        state: State, province, or region name if available. None for locations
            without state information.

    Example:
        >>> result: GeocodingResult = {
        ...     "name": "Moscow",
        ...     "local_names": {"ru": "Москва", "en": "Moscow"},
        ...     "lat": 55.7558,
        ...     "lon": 37.6173,
        ...     "country": "RU",
        ...     "state": "Moscow"
        ... }
    """

    name: str
    local_names: Dict[str, str]
    lat: float
    lon: float
    country: str
    state: Optional[str]


class CurrentWeather(TypedDict):
    """Current weather data for a location.

    Contains real-time weather conditions including temperature, wind,
    precipitation, and other meteorological measurements.

    Reference:
        https://openweathermap.org/api/one-call-3#parameter

    Attributes:
        dt: Unix timestamp of the current weather data.
        temp: Current temperature in Celsius.
        feels_like: Human-perceived temperature in Celsius, accounting for
            humidity and wind chill.
        pressure: Atmospheric pressure in hectopascals (hPa).
        humidity: Relative humidity as a percentage (0-100).
        dew_point: Dew point temperature in Celsius.
        clouds: Cloudiness percentage (0-100).
        uvi: UV index (0-11+), where higher values indicate greater UV radiation.
        visibility: Horizontal visibility in meters (maximum 10000m).
        wind_deg: Wind direction in degrees (0-360, where 0=N, 90=E, 180=S, 270=W).
        wind_speed: Wind speed in meters per second.
        wind_gust: Wind gust speed in meters per second. None if no gust data.
        sunrise: Sunrise time as Unix timestamp.
        sunset: Sunset time as Unix timestamp.
        weather_id: Weather condition code from OpenWeatherMap.
            Reference: https://openweathermap.org/weather-conditions#Weather-Condition-Codes-2
        weather_main: Weather group category (e.g., "Rain", "Snow", "Clear", "Clouds").
        weather_description: Detailed weather description (e.g., "light rain", "scattered clouds").

    Example:
        >>> weather: CurrentWeather = {
        ...     "dt": 1699123456,
        ...     "temp": 15.5,
        ...     "feels_like": 14.2,
        ...     "pressure": 1015,
        ...     "humidity": 65,
        ...     "dew_point": 8.7,
        ...     "clouds": 40,
        ...     "uvi": 2.5,
        ...     "visibility": 10000,
        ...     "wind_deg": 180,
        ...     "wind_speed": 5.2,
        ...     "wind_gust": 8.1,
        ...     "sunrise": 1699100000,
        ...     "sunset": 1699140000,
        ...     "weather_id": 500,
        ...     "weather_main": "Rain",
        ...     "weather_description": "light rain"
        ... }
    """

    dt: int
    temp: float
    feels_like: float

    pressure: int
    humidity: int
    dew_point: float
    clouds: int
    uvi: float
    visibility: int

    wind_deg: int
    wind_speed: float
    wind_gust: Optional[float]

    sunrise: int
    sunset: int

    weather_id: int
    weather_main: str
    weather_description: str


class DailyWeather(TypedDict):
    """Daily weather forecast data.

    Contains weather forecast information for a single day, including
    temperature ranges, precipitation probability, and astronomical data.

    Reference:
        https://openweathermap.org/api/one-call-3#parameter

    Attributes:
        dt: Unix timestamp for the start of the forecast day.
        temp_day: Daytime temperature in Celsius.
        temp_night: Nighttime temperature in Celsius.
        temp_eve: Evening temperature in Celsius.
        temp_morn: Morning temperature in Celsius.
        temp_min: Minimum temperature for the day in Celsius.
        temp_max: Maximum temperature for the day in Celsius.
        feels_like_day: Daytime feels-like temperature in Celsius.
        feels_like_night: Nighttime feels-like temperature in Celsius.
        feels_like_eve: Evening feels-like temperature in Celsius.
        feels_like_morn: Morning feels-like temperature in Celsius.
        pressure: Atmospheric pressure in hectopascals (hPa).
        humidity: Relative humidity as a percentage (0-100).
        dew_point: Dew point temperature in Celsius.
        clouds: Cloudiness percentage (0-100).
        uvi: UV index (0-11+), where higher values indicate greater UV radiation.
        wind_deg: Wind direction in degrees (0-360).
        wind_speed: Wind speed in meters per second.
        wind_gust: Wind gust speed in meters per second. None if no gust data.
        sunrise: Sunrise time as Unix timestamp.
        sunset: Sunset time as Unix timestamp.
        moonrise: Moonrise time as Unix timestamp.
        moonset: Moonset time as Unix timestamp.
        moon_phase: Moon phase value from 0 to 1. Values: 0 or 1 = new moon,
            0.25 = first quarter, 0.5 = full moon, 0.75 = last quarter.
        pop: Probability of precipitation as a decimal (0.0 to 1.0).
        summary: Human-readable description of the day's weather conditions.
        weather_id: Weather condition code from OpenWeatherMap.
            Reference: https://openweathermap.org/weather-conditions#Weather-Condition-Codes-2
        weather_main: Weather group category (e.g., "Rain", "Snow", "Clear").
        weather_description: Detailed weather description.

    Example:
        >>> daily: DailyWeather = {
        ...     "dt": 1699200000,
        ...     "temp_day": 18.5,
        ...     "temp_night": 12.3,
        ...     "temp_eve": 16.2,
        ...     "temp_morn": 14.1,
        ...     "temp_min": 11.8,
        ...     "temp_max": 19.2,
        ...     "feels_like_day": 17.8,
        ...     "feels_like_night": 11.5,
        ...     "feels_like_eve": 15.5,
        ...     "feels_like_morn": 13.2,
        ...     "pressure": 1018,
        ...     "humidity": 70,
        ...     "dew_point": 10.5,
        ...     "clouds": 60,
        ...     "uvi": 3.2,
        ...     "wind_deg": 200,
        ...     "wind_speed": 4.5,
        ...     "wind_gust": 7.2,
        ...     "sunrise": 1699180000,
        ...     "sunset": 1699220000,
        ...     "moonrise": 1699190000,
        ...     "moonset": 1699230000,
        ...     "moon_phase": 0.5,
        ...     "pop": 0.3,
        ...     "summary": "Partly cloudy with a chance of rain",
        ...     "weather_id": 801,
        ...     "weather_main": "Clouds",
        ...     "weather_description": "few clouds"
        ... }
    """

    dt: int
    temp_day: float
    temp_night: float
    temp_eve: float
    temp_morn: float
    temp_min: float
    temp_max: float

    feels_like_day: float
    feels_like_night: float
    feels_like_eve: float
    feels_like_morn: float

    pressure: int
    humidity: int
    dew_point: float

    clouds: int
    uvi: float

    wind_deg: int
    wind_speed: float
    wind_gust: Optional[float]

    sunrise: int
    sunset: int
    moonrise: int
    moonset: int
    moon_phase: float

    pop: float
    summary: str

    weather_id: int
    weather_main: str
    weather_description: str


class WeatherData(TypedDict):
    """Complete weather response from OpenWeatherMap API.

    Contains current weather and daily forecasts for a specific location,
    including timezone information and coordinates.

    Reference:
        https://openweathermap.org/api/one-call-3#parameter

    Attributes:
        lat: Latitude coordinate in decimal degrees.
        lon: Longitude coordinate in decimal degrees.
        timezone: IANA timezone name (e.g., "Europe/Moscow", "America/New_York").
        timezone_offset: Timezone offset from UTC in seconds. Positive for east,
            negative for west of UTC.
        current: Current weather conditions for the location.
        daily: List of daily weather forecasts. Typically contains up to 8 days
            of forecast data.

    Example:
        >>> weather_data: WeatherData = {
        ...     "lat": 55.7558,
        ...     "lon": 37.6173,
        ...     "timezone": "Europe/Moscow",
        ...     "timezone_offset": 10800,
        ...     "current": {...},  # CurrentWeather instance
        ...     "daily": [...]     # List of DailyWeather instances
        ... }
    """

    lat: float
    lon: float
    timezone: str
    timezone_offset: int
    current: CurrentWeather
    daily: List[DailyWeather]


class CombinedWeatherResult(TypedDict):
    """Combined geocoding and weather result.

    Represents a complete response that includes both the location information
    from geocoding and the weather data for that location.

    Attributes:
        location: Geocoding result containing location details and coordinates.
        weather: Complete weather data for the location.

    Example:
        >>> result: CombinedWeatherResult = {
        ...     "location": {...},  # GeocodingResult instance
        ...     "weather": {...}    # WeatherData instance
        ... }
    """

    location: GeocodingResult
    weather: WeatherData
