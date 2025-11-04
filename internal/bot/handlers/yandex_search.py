"""Yandex Search handler for Gromozeka Telegram bot.

This module provides the YandexSearchHandler class which integrates Yandex Search API
functionality into the Gromozeka bot. It enables web search capabilities through both
direct user commands and LLM tool calling.

The handler supports:
- Direct /web_search command for users to search the web
- LLM tool integration allowing the bot to search the web autonomously
- Configurable search parameters through bot configuration
- Result formatting for Telegram message display
- Content filtering for family-safe results
- Rate limiting and caching for API efficiency

Dependencies:
    - lib.yandex_search: Yandex Search API client implementation
    - internal.config.manager: Bot configuration management
    - internal.database.wrapper: Database operations
    - internal.services.llm: Language model service integration
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Sequence

import requests
from telegram import Update
from telegram.ext import ContextTypes

import lib.utils as utils
import lib.yandex_search as ys
import lib.yandex_search.xml_parser as ys_xml
from internal.config.manager import ConfigManager
from internal.database.models import (
    MessageCategory,
)
from internal.database.wrapper import DatabaseWrapper
from internal.database.yandexsearch_cache import YandexSearchCache
from internal.services.llm import LLMService
from lib.ai import (
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
)
from lib.yandex_search import YandexSearchClient

from ..models import (
    ChatSettingsKey,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
)
from .base import BaseBotHandler, commandHandlerExtended

logger = logging.getLogger(__name__)


class YandexSearchHandler(BaseBotHandler):
    """
    Handler for Yandex Search API integration in Gromozeka Telegram bot.

    This class provides web search functionality through Yandex Search API, enabling
    both direct user commands and LLM tool calling. It handles API client initialization,
    search result formatting, and integration with the bot's command system.

    The handler supports:
    - Web search via /web_search command
    - LLM tool integration for autonomous web searches
    - Configurable search parameters from bot configuration
    - Family-safe content filtering
    - Rate limiting to prevent API abuse
    - Caching for improved performance

    Attributes:
        yandexSearchClient (YandexSearchClient): Client for Yandex Search API interactions
        yandexSearchDefaults (Dict[str, Any]): Default search parameters from configuration
        llmService (LLMService): Service for LLM tool registration and management
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize the Yandex Search handler with required services and configuration.

        This method sets up the Yandex Search API client with configuration from the
        bot's configuration manager, registers the LLM tool for web search, and
        initializes default search parameters.

        Args:
            configManager (ConfigManager): Configuration manager providing bot settings
            database (DatabaseWrapper): Database wrapper for data persistence
            llmManager (LLMManager): LLM manager for AI model operations

        Raises:
            RuntimeError: If Yandex Search integration is not enabled in configuration
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        ysConfig = self.configManager.getYandexSearchConfig()
        if not ysConfig.get("enabled", False):
            logger.error("YandexSearch integration is not enabled")
            raise RuntimeError("YandexSearch integration is not enabled, can not load YandexSearchHandler")
        self.yandexSearchClient = YandexSearchClient(
            apiKey=ysConfig["api-key"],
            folderId=ysConfig["folder-id"],
            requestTimeout=int(ysConfig.get("request-timeout", 30)),
            cache=YandexSearchCache(database),
            cacheTTL=int(ysConfig.get("cache-ttl", 30)),
            useCache=True,
            rateLimitRequests=int(ysConfig.get("rate-limit-requests", 10)),
            rateLimitWindow=int(ysConfig.get("rate-limit-window", 60)),
        )
        self.yandexSearchDefaults = ysConfig.get("defaults", {})
        ys_xml.DEBUG_PRINT_FULL = bool(ysConfig.get("dump-full-xml", False))

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="web_search",
            description=(
                "Search information in Web, return list of result URLs with " "brief description of what found"
            ),
            parameters=[
                LLMFunctionParameter(
                    name="query",
                    description="Search query",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="enable_content_filter",
                    description=(
                        "If content filer should be used to not allow inapropriate content" " (Default: false)"
                    ),
                    type=LLMParameterType.BOOLEAN,
                    required=False,
                ),
            ],
            handler=self._llmToolWebSearch,
        )

        self.llmService.registerTool(
            name="get_url_content",
            description="Get the content of a URL",
            parameters=[
                LLMFunctionParameter(
                    name="url",
                    description="The URL to get the content from",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
            ],
            handler=self._llmToolGetUrlContent,
        )

    async def _llmToolWebSearch(
        self, extraData: Optional[Dict[str, Any]], query: str, enable_content_filter: bool = False, **kwargs
    ) -> str:
        """Perform web search via Yandex Search API as an LLM tool.

        This method is registered as an LLM tool, allowing the language model to
        autonomously search the web when it needs additional information. It handles
        search parameter configuration, content filtering, and result formatting
        for LLM consumption.

        Args:
            extraData (Optional[Dict[str, Any]]): Additional data passed from LLM service
            query (str): Search query text to look up on the web
            enable_content_filter (bool): Whether to enable family-safe content filtering
            **kwargs: Additional keyword arguments passed from LLM tool call

        Returns:
            str: JSON-formatted search results or error message for LLM processing
        """
        try:
            contentFilter: ys.FamilyMode = (
                ys.FamilyMode.FAMILY_MODE_MODERATE if enable_content_filter else ys.FamilyMode.FAMILY_MODE_NONE
            )
            kwargs = {**self.yandexSearchDefaults, "familyMode": contentFilter}
            ret = await self.yandexSearchClient.search(query, **kwargs)
            if ret is None:
                return utils.jsonDumps({"done": False, "errorMessage": "Failed to perform web search"})

            # Drop useless things
            ret.pop("requestId", None)
            ret.pop("foundHuman", None)
            ret.pop("page", None)

            return utils.jsonDumps({**ret, "done": "error" not in ret})
        except Exception as e:
            logger.error(f"Error searching web: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _llmToolGetUrlContent(self, extraData: Optional[Dict[str, Any]], url: str, **kwargs) -> str:
        """
        LLM tool handler to fetch content from a URL, dood!

        This tool is registered with the LLM service and can be called by AI models
        to retrieve web content during conversations. Currently returns raw content
        as a string.

        Args:
            extraData: Optional extra data passed by the LLM service (unused)
            url: The URL to fetch content from
            **kwargs: Additional keyword arguments (unused)

        Returns:
            str: The content from the URL as a string, or a JSON error object
                 if the request fails

        Note:
            TODO: Add content type checking to ensure text content is returned
        """
        # TODO: Check if content is text content
        try:
            return str(requests.get(url).content)
        except Exception as e:
            logger.error(f"Error getting content from {url}: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    def _formatSearchResult(self, searchResult: ys.SearchResponse) -> Sequence[str]:
        """Format Yandex Search API response for Telegram message display.

        This method converts the raw search response from Yandex Search API into
        a sequence of formatted strings suitable for sending as Telegram messages.
        The formatting includes result counts, error handling, and proper markdown
        formatting for links and text passages.

        Args:
            searchResult (ys.SearchResponse): Raw search response from Yandex Search API

        Returns:
            Sequence[str]: Formatted message parts ready for Telegram display.
                          First element is header with result count or error message,
                          subsequent elements are formatted result groups.
        """
        retHeader = searchResult["foundHuman"]
        if "error" in searchResult:
            error = searchResult["error"]
            retHeader += f"\nВо время поиска произошла ошибка #{error['code']}: {error['message']}"
        ret = [retHeader]

        for group in searchResult["groups"]:
            groupRets = []
            for doc in group:
                passages = "\n".join([f"* {passage}" for passage in doc["passages"]])
                cachedUrl = ""
                if "savedCopyUrl" in doc:
                    cachedUrl = f" ([кеш]({doc['savedCopyUrl']}))"
                extendedText = ""
                if "extendedText" in doc:
                    extendedText = f"> {doc['extendedText']}\n"
                docRet = (
                    f"# **[{doc['title'].replace("**", "")}]({doc['url']}){cachedUrl}**\n" + extendedText + passages
                )
                groupRets.append(docRet)

            ret.append("\n\n".join(groupRets))

        return ret

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerExtended(
        commands=("web_search",),
        shortDescription="<query> - Search Web for given query using Yandex",
        helpMessage=" `<query>`: Поискать в интернете используя Yandex Search API",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def web_search(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /web_search command for direct user web searches.

        This method processes the /web_search command, allowing users to search
        the web directly through the bot. It validates user permissions, parses
        the search query from command arguments, performs the search via Yandex
        Search API, and formats the results for Telegram display.

        Args:
            update (Update): Telegram update object containing the command message
            context (ContextTypes.DEFAULT_TYPE): Telegram context with command arguments

        Returns:
            None: This method sends messages directly via Telegram API
        """
        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_WEB_SEARCH].toBool() and not await self.isAdmin(
            ensuredMessage.user, None, True
        ):
            logger.info(f"Unauthorized /web_search command from {ensuredMessage.user} in chat {ensuredMessage.chat}")
            return

        if not context.args:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать запрос для поиска.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        searchQuery = " ".join(context.args)

        await self.startTyping(ensuredMessage)
        try:
            searchRet = await self.yandexSearchClient.search(searchQuery, **self.yandexSearchDefaults)
            if searchRet is None:
                await self.sendMessage(
                    ensuredMessage,
                    f"Не удалось ничего найти по запросу\n```\n{searchQuery}\n```\n",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

            respList = self._formatSearchResult(searchRet)
            for respMessage in respList:
                await self.sendMessage(
                    ensuredMessage,
                    respMessage,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Error while searching web: {e}")
            logger.exception(e)
            await self.sendMessage(
                ensuredMessage,
                messageText="Ошибка при поиске информации.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return
