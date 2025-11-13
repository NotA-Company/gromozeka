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

import html_to_markdown
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
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
)
from .base import BaseBotHandler, TypingManager, commandHandlerExtended

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
        )
        self.yandexSearchDefaults = ysConfig.get("defaults", {})
        ys_xml.DEBUG_PRINT_FULL = bool(ysConfig.get("dump-full-xml", False))

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="web_search",
            description=(
                "Search information in Web."
                " Return list of result URLs with"
                " brief description of what found"
                " or content from found pages"
            ),
            parameters=[
                LLMFunctionParameter(
                    name="query",
                    description="Search query",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="return_page_content",
                    description=(
                        "Should tool return full content of found documents as well?"
                        " Use it instead of downloading those documents later."
                    ),
                    type=LLMParameterType.BOOLEAN,
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
                LLMFunctionParameter(
                    name="max_results",
                    description="Maximum number of results to return (Default: 3)",
                    type=LLMParameterType.NUMBER,
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
                LLMFunctionParameter(
                    name="parse_to_markdown",
                    description="Whether to parse the content to Markdown format (Default: true)",
                    type=LLMParameterType.BOOLEAN,
                    required=False,
                ),
            ],
            handler=self._llmToolGetUrlContent,
        )

    async def _llmToolWebSearch(
        self,
        extraData: Optional[Dict[str, Any]],
        query: str,
        return_page_content: bool,
        enable_content_filter: bool = False,
        max_results: int = 5,
        **kwargs,
    ) -> str:
        """Perform web search using Yandex Search API.

        Args:
            extraData: Optional additional data for the operation
            query: Search query string
            return_page_content: Whether to download and parse content of found pages
            enable_content_filter: Whether to enable content filtering (default: False)
            max_results: Maximum number of results to return (default: 5)
            **kwargs: Additional keyword arguments

        Returns:
            JSON string containing search results or page contents with status information
        """
        try:
            max_results = min(max(1, max_results), 10)
            if return_page_content:
                # Limit max_results to 5 if return_page_content is True
                # Because of context restrictions, most of LLM's wont't be able to handle more than ~5 results
                max_results = min(max_results, 5)

            contentFilter: ys.FamilyMode = (
                ys.FamilyMode.FAMILY_MODE_MODERATE if enable_content_filter else ys.FamilyMode.FAMILY_MODE_NONE
            )
            searchKWargs = {
                **self.yandexSearchDefaults,
                "familyMode": contentFilter,
                "groupsOnPage": max_results,
            }
            searchResult = await self.yandexSearchClient.search(query, **searchKWargs)
            if searchResult is None:
                return utils.jsonDumps({"done": False, "error": "Failed to perform web search"})

            ret = {}
            if return_page_content:
                # Return content of found documents
                if "error" in searchResult:
                    ret["error"] = searchResult

                ret["pages"] = []

                for group in searchResult["groups"]:
                    for doc in group:
                        fetched = False
                        for url in [doc["url"], doc.get("savedCopyUrl", None)]:
                            if url is None:
                                continue
                            # Try URL and cachedCopy if failed
                            # url = doc["savedCopyUrl"]
                            content = await self._llmToolGetUrlContent(
                                extraData=extraData, url=url, parse_to_markdown=True
                            )
                            if content and content[0] != "{":
                                # Check that there is any result and it isn't json
                                ret["pages"].append({"url": url, "content": content})
                                fetched = True
                                break
                            else:
                                logger.warning(f"Failed to fetch content from {url}: {content}")
                        if not fetched:
                            # If fetch fails, print description
                            ret["pages"].append(
                                {
                                    "url": doc["url"],
                                    "description": doc.get("extendedText", "") + "\n" + "\n".join(doc["passages"]),
                                }
                            )

            else:
                # Return only search results
                # Drop useless things
                searchResult.pop("requestId", None)
                searchResult.pop("foundHuman", None)
                searchResult.pop("page", None)
                for groupIdx, group in enumerate(searchResult["groups"]):
                    for docIdx, doc in enumerate(group):
                        searchResult["groups"][groupIdx][docIdx].pop("savedCopyUrl", None)

                ret = searchResult

            return utils.jsonDumps({**ret, "done": "error" not in searchResult})
        except Exception as e:
            logger.error(f"Error searching web: {e}")
            return utils.jsonDumps({"done": False, "error": str(e)})

    async def _llmToolGetUrlContent(
        self,
        extraData: Optional[Dict[str, Any]],
        url: str,
        parse_to_markdown: bool = True,
        **kwargs,
    ) -> str:
        """
        LLM tool handler to fetch content from a URL, dood!

        This tool is registered with the LLM service and can be called by AI models
        to retrieve web content during conversations. Currently returns raw content
        as a string.

        Args:
            extraData: Optional extra data passed by the LLM service (unused)
            url: The URL to fetch content from
            parse_to_markdown: Whether to parse the content to Markdown (default: True)
            **kwargs: Additional keyword arguments (unused)

        Returns:
            str: The content from the URL as a string, or a JSON error object
                 if the request fails
        """
        try:
            # TODO: Switch to httpx and properly handle redirects and so on
            doc: requests.Response = requests.get(url)

            if doc.status_code < 200 or doc.status_code >= 300:
                reason = doc.reason
                if isinstance(doc.reason, bytes):
                    try:
                        reason = doc.reason.decode("utf-8")
                    except UnicodeDecodeError:
                        reason = doc.reason.decode("iso-8859-1", errors="replace")

                return utils.jsonDumps(
                    {
                        "done": False,
                        "error": f"Request failed with status {doc.status_code}: {reason}",
                    }
                )

            contentType = doc.headers.get("content-type", "text/html")
            if not contentType.startswith("text/"):
                logger.warning(f"getUrl: content type of '{url}' is {contentType}")
                return utils.jsonDumps({"done": False, "error": f"Content is not text, but {contentType}"})

            try:
                ret = doc.content.decode(doc.encoding or "utf-8")
            except Exception as e:
                logger.error(f"getUrl: cannot decode content as {doc.encoding}: {e}")
                ret = doc.content.decode("iso-8859-1", errors="replace")

            if parse_to_markdown and "html" in contentType:
                # Parse to Markdown only if it's HTML
                ret = html_to_markdown.convert(
                    ret,
                    options=html_to_markdown.ConversionOptions(
                        extract_metadata=False,
                        strip_tags={"svg", "img"},
                    ),
                )
            return ret
        except Exception as e:
            logger.error(f"Error getting content from {url}: {e}")
            return utils.jsonDumps({"done": False, "error": str(e)})

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
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
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
        if not context.args:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать запрос для поиска.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        searchQuery = " ".join(context.args)

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
