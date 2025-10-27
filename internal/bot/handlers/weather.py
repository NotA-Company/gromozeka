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

import datetime
import logging

from typing import Any, Dict, Optional

from telegram import Chat, Update
from telegram.ext import ContextTypes

from internal.services.llm.service import LLMService

from .base import BaseBotHandler, HandlerResultStatus

from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
)
from lib.ai.manager import LLMManager
from lib.openweathermap.client import OpenWeatherMapClient
from lib.openweathermap.models import CombinedWeatherResult
import lib.utils as utils

from internal.config.manager import ConfigManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.openweathermap_cache import DatabaseWeatherCache
from internal.database.models import (
    MessageCategory,
)

from ..models import (
    ChatSettingsKey,
    CommandCategory,
    CommandHandlerOrder,
    EnsuredMessage,
    commandHandler,
)
from .. import constants

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
            cache=DatabaseWeatherCache(self.db),
            geocodingTTL=openWeatherMapConfig.get("geocoding-cache-ttl", None),
            weatherTTL=openWeatherMapConfig.get("weather-cache-ttl", None),
            requestTimeout=openWeatherMapConfig.get("request-timeout", 10),
            defaultLanguage=openWeatherMapConfig.get("default-language", "ru"),
        )

        self.llmService = LLMService.getInstance()

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
            if self.openWeatherMapClient is None:
                return utils.jsonDumps({"done": False, "errorMessage": "OpenWeatherMapClient is not set"})

            ret = await self.openWeatherMapClient.getWeatherByCity(city, countryCode)
            if ret is None:
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
            if self.openWeatherMapClient is None:
                return utils.jsonDumps({"done": False, "errorMessage": "OpenWeatherMapClient is not set"})

            ret = await self.openWeatherMapClient.getWeather(lat, lon)
            if ret is None:
                return utils.jsonDumps({"done": False, "errorMessage": "Failed to get weather"})

            return utils.jsonDumps({**ret, "done": True})
        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _formatWeather(self, weatherData: CombinedWeatherResult) -> str:
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
        cityName = weatherData["location"]["local_names"].get("ru", weatherData["location"]["name"])
        country = weatherData["location"]["country"]
        # TODO: add convertation from code to name
        weatherCurrent = weatherData["weather"]["current"]
        weatherTime = str(datetime.datetime.fromtimestamp(weatherCurrent["dt"], tz=datetime.timezone.utc))
        pressureMmHg = int(weatherCurrent["pressure"] * constants.HPA_TO_MMHG)
        sunriseTime = datetime.datetime.fromtimestamp(weatherCurrent["sunrise"], tz=datetime.timezone.utc).timetz()
        sunsetTime = datetime.datetime.fromtimestamp(weatherCurrent["sunset"], tz=datetime.timezone.utc).timetz()
        return (
            f"Погода в городе **{cityName}**, {country} на **{weatherTime}**:\n\n"
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

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """Handle natural language weather requests in messages, dood!

        Processes messages that mention the bot and contain weather-related queries
        in Russian. Supports patterns like "погода в [город]" and "какая погода в [город]".

        Args:
            update: Telegram update object
            context: Telegram context for the handler
            ensuredMessage: Validated message object with user and chat info

        Returns:
            HandlerResultStatus indicating the result:
            - FINAL: Weather request was processed and response sent
            - SKIPPED: Message doesn't match weather request pattern
            - ERROR: Failed to process weather request or ensuredMessage is None

        Note:
            - Only processes messages in PRIVATE, GROUP, or SUPERGROUP chats
            - Requires bot to be mentioned at the beginning of the message
            - Supports city name with optional country code (comma-separated)
            - Logs warning if weather data cannot be retrieved
        """
        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        chatType = ensuredMessage.chat.type

        if chatType not in [Chat.PRIVATE, Chat.GROUP, Chat.SUPERGROUP]:
            return HandlerResultStatus.SKIPPED

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_MENTION].toBool():
            return HandlerResultStatus.SKIPPED

        mentionedMe = self.checkEMMentionsMe(ensuredMessage)
        if not mentionedMe.restText or (
            not mentionedMe.byNick and (not mentionedMe.byName or mentionedMe.byName[0] > 0)
        ):
            return HandlerResultStatus.SKIPPED
        # Proceed only if there is restText
        #  + mentioned at begin of message (byNick is always at begin of message, so not separate check needed)

        restText = mentionedMe.restText
        restTextLower = restText.lower()

        # Weather
        weatherRequestList = [
            "какая погода в городе ",
            "какая погода в ",
            "погода в городе ",
            "погода в ",
        ]
        isWeatherRequest = False
        reqContent = ""
        for weatherReq in weatherRequestList:
            if restTextLower.startswith(weatherReq):
                reqContent = restText[len(weatherReq) :].strip().rstrip(" ?")
                if reqContent:
                    isWeatherRequest = True
                    break

        if not isWeatherRequest or not reqContent:
            return HandlerResultStatus.SKIPPED

        weatherLocation = reqContent.split(",")
        city = weatherLocation[0].strip()
        countryCode = None
        if len(weatherLocation) > 1:
            countryCode = weatherLocation[1].strip()

        # TODO: Try to convert city to initial form (Москве -> Москва)
        # TODO: Try to convert country to country code (Россия -> RU)

        weatherData = await self.openWeatherMapClient.getWeatherByCity(city, countryCode)
        if weatherData is None:
            logger.warning(f"Wasn't able to get weather for {city}, {countryCode}")
            return HandlerResultStatus.ERROR

        await self.sendMessage(
            ensuredMessage,
            await self._formatWeather(weatherData),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        return HandlerResultStatus.FINAL

    ###
    # COMMANDS Handlers
    ###

    @commandHandler(
        commands=("weather",),
        shortDescription="<city> [, <countryCode>] - Get weather for given city",
        helpMessage=" `<city>` `[, <countryCode>]`: Показать погоду в указанном городе "
        "(можно добавить 2х-буквенный код страны для уточнения).",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def weather_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_WEATHER].toBool() and not await self.isAdmin(
            ensuredMessage.user, None, True
        ):
            logger.info(f"Unauthorized /weather command from {ensuredMessage.user} in chat {ensuredMessage.chat}")
            return

        city = ""
        countryCode: Optional[str] = None

        if context.args:
            argsStr = " ".join(context.args)
            commaSplitted = argsStr.split(",")
            city = commaSplitted[0]
            if len(commaSplitted) > 1:
                countryCode = commaSplitted[1]
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать город для получения погоды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        try:
            weatherData = await self.openWeatherMapClient.getWeatherByCity(city, countryCode)
            if weatherData is None:
                await self.sendMessage(
                    ensuredMessage,
                    f"Не удалось получить погоду для города {city}",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

            resp = await self._formatWeather(weatherData)

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
