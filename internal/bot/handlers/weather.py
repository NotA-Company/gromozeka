"""Weather handler module for Gromozeka bot, dood!

This module provides weather-related functionality through OpenWeatherMap API integration.
It handles weather commands, message-based weather requests, and registers LLM tools
for weather data retrieval by city name or coordinates.

The module includes:
- Weather command handler (/weather)
- Natural language weather request processing
- LLM tool registration for AI-powered weather queries
- Weather data formatting and presentation

Dependencies:
    - OpenWeatherMap API (requires valid API key)
    - Database for caching weather and geocoding data
    - LLM service for tool registration
"""

# TODO: rewrite all docstrings and make them more compact

import datetime
import logging
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

import lib.utils as utils
from internal.config.manager import ConfigManager
from internal.database.generic_cache import GenericDatabaseCache
from internal.database.models import (
    CacheType,
    MessageCategory,
)
from internal.database.wrapper import DatabaseWrapper
from internal.services.llm import LLMService
from lib.ai import (
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
)
from lib.cache import JsonKeyGenerator, JsonValueConverter, StringKeyGenerator
from lib.geocode_maps import GeocodeMapsClient
from lib.openweathermap import OpenWeatherMapClient, WeatherData

from .. import constants
from ..models import (
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
)
from .base import BaseBotHandler, TypingManager, commandHandlerExtended

logger = logging.getLogger(__name__)


class WeatherHandler(BaseBotHandler):
    """Handler for weather-related bot functionality, dood!

    This class manages all weather-related operations including:
    - Processing /weather commands
    - Handling natural language weather requests in messages
    - Registering and managing LLM tools for weather queries
    - Formatting and presenting weather data to users

    The handler integrates with OpenWeatherMap API and provides caching
    through the database layer for improved performance.

    Attributes:
        openWeatherMapClient: Client for OpenWeatherMap API interactions
        llmService: Service for LLM tool registration and management
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize weather handler with required dependencies, dood!

        Sets up OpenWeatherMap client with configuration and caching,
        and registers LLM tools for weather data retrieval.

        Args:
            configManager: Configuration manager for accessing OpenWeatherMap settings
            database: Database wrapper for caching and data persistence
            llmManager: LLM manager for model interactions

        Raises:
            RuntimeError: If OpenWeatherMap integration is not enabled in configuration
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        openWeatherMapConfig = self.configManager.getOpenWeatherMapConfig()
        if not openWeatherMapConfig.get("enabled", False):
            logger.error("OpenWeatherMap integration is not enabled")
            raise RuntimeError("OpenWeatherMap integration is not enabled, can not load WeatherHandler")

        self.openWeatherMapClient = OpenWeatherMapClient(
            apiKey=openWeatherMapConfig["api-key"],
            weatherCache=GenericDatabaseCache(
                self.db,
                CacheType.WEATHER,
                keyGenerator=StringKeyGenerator(),
                valueConverter=JsonValueConverter(),
            ),
            geocodingCache=GenericDatabaseCache(
                self.db,
                CacheType.GEOCODING,
                keyGenerator=StringKeyGenerator(),
                valueConverter=JsonValueConverter(),
            ),
            geocodingTTL=openWeatherMapConfig.get("geocoding-cache-ttl", None),
            weatherTTL=openWeatherMapConfig.get("weather-cache-ttl", None),
            requestTimeout=openWeatherMapConfig.get("request-timeout", 10),
            defaultLanguage=openWeatherMapConfig.get("default-language", "ru"),
            rateLimiterQueue=openWeatherMapConfig.get("ratelimiter-queue", "openweathermap"),
        )

        self.geocodeMapsClient: Optional[GeocodeMapsClient] = None
        geocodeMapsConfig = self.configManager.getGeocodeMapsConfig()
        # logger.debug(f"geocoderConfig: {utils.jsonDumps(geocodeMapsConfig, indent=2)}")
        if geocodeMapsConfig.get("enabled"):
            geocodeTTL = int(geocodeMapsConfig.get("cache-ttl", 2592000))
            self.geocodeMapsClient = GeocodeMapsClient(
                apiKey=geocodeMapsConfig["api-key"],
                searchCache=GenericDatabaseCache(
                    self.db, CacheType.GM_SEARCH, keyGenerator=JsonKeyGenerator(), valueConverter=JsonValueConverter()
                ),
                reverseCache=GenericDatabaseCache(
                    self.db, CacheType.GM_REVERSE, keyGenerator=JsonKeyGenerator(), valueConverter=JsonValueConverter()
                ),
                lookupCache=GenericDatabaseCache(
                    self.db, CacheType.GM_LOOKUP, keyGenerator=JsonKeyGenerator(), valueConverter=JsonValueConverter()
                ),
                searchTTL=geocodeTTL,
                reverseTTL=geocodeTTL,
                lookupTTL=geocodeTTL,
                requestTimeout=geocodeMapsConfig.get("request-timeout", 10),
                rateLimiterQueue=geocodeMapsConfig.get("ratelimiter-queue", "geocode-maps"),
                acceptLanguage=geocodeMapsConfig.get("accept-language", "ru"),
            )

        self.llmService = LLMService.getInstance()

        if self.geocodeMapsClient is None:
            # No Geocode Maps client, use simpler geocoder
            self.llmService.registerTool(
                name="get_weather_by_city",
                description=(
                    "Get weather and forecast for given city. Return JSON of current weather "
                    "and weather forecast for next following days. "
                    "Temperature returned in Celsius."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="city",
                        description="City to get weather in",
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="countryCode",
                        description="ISO 3166 country code of city",
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                ],
                handler=self._llmToolGetWeatherByCity,
            )
        else:
            # Geocode Maps client activated - we can geocode any address
            self.llmService.registerTool(
                name="get_weather_by_address",
                description=(
                    "Get weather and forecast for given address or city. Return JSON of current weather "
                    "and weather forecast for next following days. "
                    "Temperature returned in Celsius."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="address_or_city",
                        description="Free-form address search query (For example: [<address>] <City>[, <Country>])",
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                ],
                handler=self._llmToolGetWeatherByAddress,
            )

        self.llmService.registerTool(
            name="get_weather_by_coords",
            description=(
                "Get weather and forecast for given location. Return JSON of current weather "
                "and weather forecast for next following days. "
                "Temperature returned in Celsius."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="lat",
                    description="Latitude of location",
                    type=LLMParameterType.NUMBER,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="lon",
                    description="Longitude of location",
                    type=LLMParameterType.NUMBER,
                    required=True,
                ),
            ],
            handler=self._llmToolGetWeatherByCoords,
        )

    async def _llmToolGetWeatherByCity(
        self, extraData: Optional[Dict[str, Any]], city: str, countryCode: Optional[str] = None, **kwargs
    ) -> str:
        """LLM tool handler for retrieving weather by city name, dood!

        This method is registered as an LLM tool and can be called by the AI
        to fetch weather data for a specified city. It returns JSON-formatted
        weather information including current conditions and forecast.

        Args:
            extraData: Optional extra data passed by LLM service
            city: Name of the city to get weather for
            countryCode: Optional ISO 3166 country code for disambiguation
            **kwargs: Additional keyword arguments (ignored)

        Returns:
            JSON string containing weather data with structure:
            - done: Boolean indicating success
            - location: Geocoding information
            - weather: Current weather and forecast data
            - errorMessage: Error description if done is False

        Note:
            Filters location local_names to reduce context size by keeping
            only languages defined in constants.GEOCODER_LOCATION_LANGS.
        """
        try:
            ret = await self.openWeatherMapClient.getWeatherByCity(city, countryCode)
            if ret is None:
                logger.error(f"Weather API returned None for city: {city}, country: {countryCode}")
                return utils.jsonDumps({"done": False, "errorMessage": "Failed to get weather"})

            # Drop useless local_names to decrease context
            for lang in list(ret["location"]["local_names"].keys()):
                if lang not in constants.GEOCODER_LOCATION_LANGS:
                    ret["location"]["local_names"].pop(lang, None)

            return utils.jsonDumps({**ret, "done": True})
        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _llmToolGetWeatherByCoords(
        self, extraData: Optional[Dict[str, Any]], lat: float, lon: float, **kwargs
    ) -> str:
        """LLM tool handler for retrieving weather by coordinates, dood!

        This method is registered as an LLM tool and can be called by the AI
        to fetch weather data for a specific geographic location using latitude
        and longitude coordinates.

        Args:
            extraData: Optional extra data passed by LLM service
            lat: Latitude of the location
            lon: Longitude of the location
            **kwargs: Additional keyword arguments (ignored)

        Returns:
            JSON string containing weather data with structure:
            - done: Boolean indicating success
            - weather: Current weather and forecast data
            - errorMessage: Error description if done is False
        """
        try:
            ret = await self.openWeatherMapClient.getWeather(lat, lon)
            if ret is None:
                return utils.jsonDumps({"done": False, "errorMessage": "Failed to get weather"})

            return utils.jsonDumps({**ret, "done": True})
        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _llmToolGetWeatherByAddress(
        self, extraData: Optional[Dict[str, Any]], address_or_city: str, **kwargs
    ) -> str:
        """TODO"""
        try:
            if self.geocodeMapsClient is None:
                logger.error("Geocode Maps Client is not initialized somehow")
                raise ValueError("Geocode Maps Client is not initialized")

            geocodeRet = await self.geocodeMapsClient.search(address_or_city)
            if not geocodeRet:
                logger.error(f"Geocode Maps API returned '{geocodeRet}' for '{address_or_city}'")
                return utils.jsonDumps({"done": False, "error": "Failed to locate given address"})
            firstGeocodeRet = geocodeRet[0]
            lat = float(firstGeocodeRet["lat"])
            lon = float(firstGeocodeRet["lon"])
            weatherRet = await self.openWeatherMapClient.getWeather(lat=lat, lon=lon)
            if weatherRet is None:
                logger.error(f"Weather API returned None for : {lat}:{lon} ({address_or_city})")
                return utils.jsonDumps({"done": False, "error": "Failed to get weather"})

            # Drop useless fields to reduce context
            compactedGeocodeRet = {}
            for k in ["osm_type", "lat", "lon", "category", "type", "addresstype", "name", "address", "extratags"]:
                if k in firstGeocodeRet:
                    compactedGeocodeRet[k] = firstGeocodeRet[k]

            if "namedetails" in firstGeocodeRet:
                neededLangs = [
                    f"name:{k}" for k in constants.GEOCODER_LOCATION_LANGS + [self.geocodeMapsClient.acceptLanguage]
                ] + ["name", "int_name"]
                compactedGeocodeRet["namedetails"] = {k: v for k, v in firstGeocodeRet.items() if k in neededLangs}

            for k in ["lon", "lat"]:
                weatherRet.pop(k, None)

            return utils.jsonDumps(
                {
                    "location": compactedGeocodeRet,
                    "weather": weatherRet,
                    "done": True,
                }
            )
        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _formatWeather(self, weatherData: WeatherData, city: str, country: str) -> str:
        """Format weather data for user-friendly presentation, dood!

        Converts raw weather API response into a formatted markdown string
        with current weather conditions, temperature, pressure, humidity,
        wind, UV index, and sunrise/sunset times.

        Args:
            weatherData: Combined weather result from OpenWeatherMap API containing
                        location info and current weather data

        Returns:
            Markdown-formatted string with weather information in Russian,
            including:
            - City name and country
            - Weather description and cloud coverage
            - Temperature (actual and feels-like)
            - Pressure in mmHg
            - Humidity percentage
            - UV index
            - Wind direction and speed
            - Sunrise and sunset times

        Note:
            - Pressure is converted from hPa to mmHg using HPA_TO_MMHG constant
            - Times are displayed in UTC timezone
            - City name prefers Russian localization if available
        """
        # TODO: add convertation from code to name
        weatherCurrent = weatherData["current"]
        weatherTime = str(datetime.datetime.fromtimestamp(weatherCurrent["dt"], tz=datetime.timezone.utc))
        pressureMmHg = int(weatherCurrent["pressure"] * constants.HPA_TO_MMHG)
        sunriseTime = datetime.datetime.fromtimestamp(weatherCurrent["sunrise"], tz=datetime.timezone.utc).timetz()
        sunsetTime = datetime.datetime.fromtimestamp(weatherCurrent["sunset"], tz=datetime.timezone.utc).timetz()
        return (
            f"Погода в городе **{city}**, {country} на **{weatherTime}**:\n\n"
            f"{weatherCurrent['weather_description'].capitalize()}, облачность {weatherCurrent['clouds']}%\n"
            f"**Температура**: _{weatherCurrent['temp']} °C_\n"
            f"**Ощущается как**: _{weatherCurrent['feels_like']} °C_\n"
            f"**Давление**: _{pressureMmHg} мм рт. ст._\n"
            f"**Влажность**: _{weatherCurrent['humidity']}%_\n"
            f"**УФ-Индекс**: _{weatherCurrent['uvi']}_\n"
            f"**Ветер**: _{weatherCurrent['wind_deg']}°, {weatherCurrent['wind_speed']} м/с_\n"
            f"**Восход**: _{sunriseTime}_\n"
            f"**Закат**: _{sunsetTime}_\n"
        )

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerExtended(
        commands=("weather",),
        shortDescription="<address> - Get weather for given address",
        helpMessage=" `<address>`: Показать погоду по указанному адресу.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def weather_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /weather command for retrieving weather information, dood!

        Processes the /weather command with city name and optional country code
        to fetch and display current weather conditions and forecast.

        Command format: /weather <city> [, <countryCode>]

        Args:
            update: Telegram update object containing the command message
            context: Telegram context with command arguments in context.args

        Returns:
            None. Sends weather information or error message to the chat.

        Behavior:
            - Validates chat settings for weather command permission
            - Requires admin privileges if weather is disabled in chat settings
            - Parses city name and optional country code from arguments
            - Fetches weather data from OpenWeatherMap API
            - Formats and sends weather information as markdown
            - Handles errors gracefully with user-friendly messages

        Error cases:
            - No arguments provided: Prompts user to specify city
            - OpenWeatherMap client not configured: Notifies about missing setup
            - Weather data unavailable: Informs about retrieval failure
            - Exception during processing: Logs error and notifies user

        Note:
            - Saves command message to database with USER_COMMAND category
            - Response is saved with BOT_COMMAND_REPLY or BOT_ERROR category
            - Country code should be ISO 3166 format (e.g., RU, US, GB)
        """
        # Get Weather for given city (and country)
        address = ""

        if context.args:
            address = " ".join(context.args)
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать адрес для получения погоды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        try:
            lon: Optional[float] = None
            lat: Optional[float] = None
            city: str = ""
            country: str = ""

            if self.geocodeMapsClient is None:
                commaSplittedAddress = address.split(",")
                city = commaSplittedAddress[0]
                countryCode: Optional[str] = None
                if len(commaSplittedAddress) > 1:
                    countryCode = commaSplittedAddress[1]
                cityLocation = await self.openWeatherMapClient.getCoordinates(city=city, country=countryCode)
                if cityLocation is not None:
                    lon = cityLocation["lon"]
                    lat = cityLocation["lat"]
                    city = cityLocation["local_names"].get("ru", cityLocation["name"])
                    country = cityLocation["country"]
            else:
                geocodeRet = await self.geocodeMapsClient.search(address)
                if geocodeRet:
                    # logger.debug(f"Got location: {utils.jsonDumps(geocodeRet, indent=2)}")
                    lat = float(geocodeRet[0]["lat"])
                    lon = float(geocodeRet[0]["lon"])
                    city = geocodeRet[0]["address"].get("city", "")
                    country = geocodeRet[0]["address"].get("country", "")

            if lon is None or lat is None:
                await self.sendMessage(
                    ensuredMessage,
                    "Не удалось найти указанный адрес",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

            weatherRet = await self.openWeatherMapClient.getWeather(lat=lat, lon=lon)
            if weatherRet is None:
                await self.sendMessage(
                    ensuredMessage,
                    "Не удалось получить погоду для указанного адреса",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

            resp = await self._formatWeather(weatherRet, city=city, country=country)

            await self.sendMessage(
                ensuredMessage,
                resp,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        except Exception as e:
            logger.error(f"Error while getting weather: {e}")
            logger.exception(e)
            await self.sendMessage(
                ensuredMessage,
                messageText="Ошибка при получении погоды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return
