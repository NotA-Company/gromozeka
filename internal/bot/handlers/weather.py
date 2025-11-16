"""Weather handler for Gromozeka bot with OpenWeatherMap API integration.

Provides weather commands, LLM tools for weather queries, and data formatting.
Requires OpenWeatherMap API key, database for caching, and LLM service.
"""

import asyncio
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
    """Handler for weather-related bot functionality.

    Manages weather commands, LLM tools, and data formatting.
    Integrates with OpenWeatherMap API and provides caching.

    Attributes:
        openWeatherMapClient: OpenWeatherMap API client
        llmService: LLM tool registration service
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize weather handler with dependencies.

        Sets up OpenWeatherMap client with caching and registers LLM tools.

        Args:
            configManager: Configuration manager for OpenWeatherMap settings
            database: Database wrapper for caching
            llmManager: LLM manager for model interactions

        Raises:
            RuntimeError: If OpenWeatherMap integration is disabled
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
                    self.db,
                    CacheType.GM_SEARCH,
                    keyGenerator=JsonKeyGenerator(hash=False),
                    valueConverter=JsonValueConverter(),
                ),
                reverseCache=GenericDatabaseCache(
                    self.db,
                    CacheType.GM_REVERSE,
                    keyGenerator=JsonKeyGenerator(hash=False),
                    valueConverter=JsonValueConverter(),
                ),
                lookupCache=GenericDatabaseCache(
                    self.db,
                    CacheType.GM_LOOKUP,
                    keyGenerator=JsonKeyGenerator(hash=False),
                    valueConverter=JsonValueConverter(),
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
        """LLM tool handler for retrieving weather by city name.

        Fetches weather data for specified city and returns JSON-formatted results.

        Args:
            extraData: Optional extra data from LLM service
            city: City name to get weather for
            countryCode: Optional ISO 3166 country code
            **kwargs: Additional arguments (ignored)

        Returns:
            JSON string with weather data containing:
            - done: Success status
            - location: Geocoding info
            - weather: Current weather and forecast
            - errorMessage: Error description if failed
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
        """LLM tool handler for retrieving weather by coordinates.

        Fetches weather data for specific geographic coordinates.

        Args:
            extraData: Optional extra data from LLM service
            lat: Latitude of location
            lon: Longitude of location
            **kwargs: Additional arguments (ignored)

        Returns:
            JSON string with weather data containing:
            - done: Success status
            - weather: Current weather and forecast
            - errorMessage: Error description if failed
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
        """LLM tool handler for retrieving weather by address.

        Geocodes address and fetches weather data for the location.

        Args:
            extraData: Optional extra data from LLM service
            address_or_city: Free-form address search query
            **kwargs: Additional arguments (ignored)

        Returns:
            JSON string with weather data containing:
            - done: Success status
            - location: Geocoding info
            - weather: Current weather and forecast
            - errorMessage: Error description if failed
        """
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

    async def _formatWeather(self, weatherData: WeatherData, location: str) -> str:
        """Format weather data for user-friendly presentation.

        Converts weather API response to formatted markdown string with conditions,
        temperature, pressure, humidity, wind, UV index, and sunrise/sunset.

        Args:
            weatherData: Weather result from OpenWeatherMap API
            location: Location name

        Returns:
            Markdown-formatted string in Russian with weather info including
            city, conditions, temperature, pressure, humidity, UV, wind, and times.
        """
        # TODO: add convertation from code to name
        tzOffset = weatherData["timezone_offset"]
        targetTZ = datetime.timezone(datetime.timedelta(seconds=tzOffset))
        weatherCurrent = weatherData["current"]

        weatherTime = str(
            datetime.datetime.fromtimestamp(weatherCurrent["dt"], tz=datetime.timezone.utc).astimezone(targetTZ)
        )
        pressureMmHg = int(weatherCurrent["pressure"] * constants.HPA_TO_MMHG)
        sunriseTime = (
            datetime.datetime.fromtimestamp(weatherCurrent["sunrise"], tz=datetime.timezone.utc)
            .astimezone(targetTZ)
            .timetz()
        )
        sunsetTime = (
            datetime.datetime.fromtimestamp(weatherCurrent["sunset"], tz=datetime.timezone.utc)
            .astimezone(targetTZ)
            .timetz()
        )
        return (
            f"Погода в **{location}** на **{weatherTime}**:\n\n"
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
        """Handle /weather command for retrieving weather information.

        Processes /weather command with address to fetch and display weather.

        Args:
            ensuredMessage: Message wrapper for sending responses
            typingManager: Typing indicator manager
            update: Telegram update object
            context: Telegram context with command arguments

        Returns:
            None. Sends weather info or error message to chat.
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
            locationStr: str = ""
            # country: str = ""

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
                    locationStr = cityLocation["local_names"].get("ru", cityLocation["name"])
                    # country = cityLocation["country"]
            else:
                geocodeRet = await self.geocodeMapsClient.search(address)
                if geocodeRet:
                    # logger.debug(f"Got location: {utils.jsonDumps(geocodeRet, indent=2)}")
                    lat = float(geocodeRet[0]["lat"])
                    lon = float(geocodeRet[0]["lon"])
                    locationStr = geocodeRet[0].get("display_name", "")
                    if not locationStr:
                        locationStr = geocodeRet[0]["address"].get("city", "")
                    # country = geocodeRet[0]["address"].get("country", "")

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

            resp = await self._formatWeather(weatherRet, location=locationStr)

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

    @commandHandlerExtended(
        commands=("geocode",),
        shortDescription="[short] <address> - Return geocoding result for given address",
        helpMessage=(" [`short`] `<address>`: Показать результат геокодинга для указанного адреса. " "Если передан параметр `short`, то выводит только основную информацию."),
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def geocode_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /geocode command for retrieving geocoding information.

        Processes /geocode command with address to fetch and display geocoding results.

        Args:
            ensuredMessage: Message wrapper for sending responses
            typingManager: Typing indicator manager
            update: Telegram update object
            context: Telegram context with command arguments

        Returns:
            None. Sends geocoding info or error message to chat.
        """
        address = ""
        isShort = False
        args = context.args
        if args:
            if args[0].strip().lower() == "short":
                isShort = True
                args = args[1:]
            address = " ".join(args)
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать адрес для получения данных.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if self.geocodeMapsClient is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Провайдер геокодинга не настроен.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        try:
            geocodeRet = await self.geocodeMapsClient.search(address)
            if not geocodeRet:
                await self.sendMessage(
                    ensuredMessage,
                    "Не удалось найти указанный адрес",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

            for geocode in geocodeRet:
                if isShort:
                    geocode.pop("address", None)
                await self.sendMessage(
                    ensuredMessage,
                    f"```json\n{utils.jsonDumps(geocode, indent=2)}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Error while getting weather: {e}")
            logger.exception(e)
            await self.sendMessage(
                ensuredMessage,
                messageText="Ошибка при получении погоды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return