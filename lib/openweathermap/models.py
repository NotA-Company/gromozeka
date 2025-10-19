"""
Data models for OpenWeatherMap API client

This module defines TypedDict classes for API responses and cache entries.
All models follow the OpenWeatherMap API v3.0 specification.
"""

from typing import Dict, Optional, TypedDict, List

# API Response Models


class GeocodingResult(TypedDict):
    """Result from geocoding API"""

    name: str  # City name (English)
    local_names: Dict[str, str]  # Names in different languages {"ru": "Москва", "en": "Moscow"}
    lat: float  # Latitude
    lon: float  # Longitude
    country: str  # Country code (e.g., "RU")
    state: Optional[str]  # State/region name (if available)


class CurrentWeather(TypedDict):
    """Current weather data"""

    # https://openweathermap.org/api/one-call-3#parameter

    dt: int  # Unix timestamp
    temp: float  # Temperature (Celsius)
    feels_like: float  # Feels like temperature (Celsius)

    pressure: int  # Atmospheric pressure (hPa)
    humidity: int  # Humidity percentage
    dew_point: float  # Dew point (Celsius)
    clouds: int  # Cloudiness percentage
    uvi: float  # UV index
    visibility: int  # Visibility (meters) max 10Km

    wind_deg: int  # Wind direction (degrees)
    wind_speed: float  # Wind speed (m/s)
    wind_gust: Optional[float]  # Wind gust (m/s)

    sunrise: int  # Sunrise time (Unix timestamp)
    sunset: int  # Sunset time (Unix timestamp)

    # https://openweathermap.org/weather-conditions#Weather-Condition-Codes-2
    weather_id: int  # Weather condition ID
    weather_main: str  # Weather group (Rain, Snow, Clear, etc.)
    weather_description: str  # Weather description


class DailyWeather(TypedDict):
    """Daily weather forecast"""

    # https://openweathermap.org/api/one-call-3#parameter

    dt: int  # Unix timestamp
    temp_day: float  # Day temperature (Celsius)
    temp_night: float  # Night temperature (Celsius)
    temp_eve: float  # Evening temperature (Celsius)
    temp_morn: float  # Morning temperature (Celsius)
    temp_min: float  # Min temperature (Celsius)
    temp_max: float  # Max temperature (Celsius)

    feels_like_day: float  # Day feels like temperature (Celsius)
    feels_like_night: float  # Night feels like temperature (Celsius)
    feels_like_eve: float  # Evening feels like temperature (Celsius)
    feels_like_morn: float  # Morning feels like temperature (Celsius)

    pressure: int  # Atmospheric pressure (hPa)
    humidity: int  # Humidity percentage (%)
    dew_point: float  # Dew point (Celsius)

    clouds: int  # Cloudiness percentage (%)
    uvi: float  # UV index

    wind_deg: int  # Wind direction (degrees)
    wind_speed: float  # Wind speed (m/s)
    wind_gust: Optional[float]  # Wind gust (m/s)

    sunrise: int  # Sunrise time (Unix timestamp)
    sunset: int  # Sunset time (Unix timestamp)
    moonrise: int  # Moonrise time (Unix timestamp)
    moonset: int  # Moonset time (Unix timestamp)
    moon_phase: float  # Moon phase (0-1) (0, 1 - new moon, 0.25 - first quarter, 0.5 - full moon, 0.75 - last quarter)

    pop: float  # Probability of precipitation (0-1)
    summary: str  # Human-readable description of the weather conditions for the day

    # https://openweathermap.org/weather-conditions#Weather-Condition-Codes-2
    weather_id: int  # Weather condition ID
    weather_main: str  # Weather group
    weather_description: str  # Weather description


class WeatherData(TypedDict):
    """Complete weather response"""

    # https://openweathermap.org/api/one-call-3#parameter

    lat: float  # Latitude
    lon: float  # Longitude
    timezone: str  # Timezone name
    timezone_offset: int  # Timezone offset in seconds
    current: CurrentWeather  # Current weather data
    daily: List[DailyWeather]  # Up to 8 days


class CombinedWeatherResult(TypedDict):
    """Combined geocoding + weather result"""

    location: GeocodingResult
    weather: WeatherData
