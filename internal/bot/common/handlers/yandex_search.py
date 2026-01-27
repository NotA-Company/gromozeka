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
from typing import Any, Dict, List, Optional, Sequence

import html_to_markdown
import httpx

import lib.utils as utils
import lib.yandex_search as ys
import lib.yandex_search.xml_parser as ys_xml
from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.bot.models.chat_settings import ChatSettingsKey
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
from lib.ai.models import ModelMessage, ModelResultStatus
from lib.cache import JsonKeyGenerator, JsonValueConverter, StringKeyGenerator, StringValueConverter
from lib.yandex_search import SearchRequestKeyGenerator, YandexSearchClient

from .base import BaseBotHandler

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

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
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
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        ysConfig = self.configManager.getYandexSearchConfig()
        if not ysConfig.get("enabled", False):
            logger.error("YandexSearch integration is not enabled")
            raise RuntimeError("YandexSearch integration is not enabled, can not load YandexSearchHandler")
        self.yandexSearchClient = YandexSearchClient(
            apiKey=ysConfig["api-key"],
            folderId=ysConfig["folder-id"],
            requestTimeout=int(ysConfig.get("request-timeout", 30)),
            cache=GenericDatabaseCache(
                database,
                namespace=CacheType.YANDEX_SEARCH,
                keyGenerator=SearchRequestKeyGenerator(),
                valueConverter=JsonValueConverter(),
            ),
            cacheTTL=int(ysConfig.get("cache-ttl", 30)),
            rateLimiterQueue=ysConfig.get("ratelimiter-queue", "yandex-search"),
        )
        self.yandexSearchDefaults = ysConfig.get("defaults", {})
        ys_xml.DEBUG_PRINT_FULL = bool(ysConfig.get("dump-full-xml", False))

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="web_search",
            description=(
                "Search information in Web. "
                "Return list of result URLs with brief description of what found"
                " or content from found pages. "
                "Use this tool when user asks for it or when"
                " you do not know answer but think, that it could be found in Internet."
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
                LLMFunctionParameter(
                    name="max_size",
                    description="Max size of returned content. "
                    "It will be condensed if page content is bigger than it (Default: 10240)",
                    type=LLMParameterType.NUMBER,
                    required=False,
                ),
            ],
            handler=self._llmToolGetUrlContent,
        )

        self.urlContentCache = GenericDatabaseCache(
            database,
            namespace=CacheType.URL_CONTENT,
            keyGenerator=StringKeyGenerator(),
            valueConverter=JsonValueConverter[Dict[str, Any]](),
        )
        self.urlContentCondensedCache = GenericDatabaseCache(
            database,
            namespace=CacheType.URL_CONTENT_CONDENSED,
            keyGenerator=JsonKeyGenerator[Dict[str, Any]](hash=False),
            valueConverter=StringValueConverter(),
        )
        self.urlContentCacheTTL = 60 * 60  # 1 Hour

        # End of __init__

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

        async def fetchUrlContent(urls: Sequence[Optional[str]]) -> Optional[Dict[str, str]]:
            try:
                for url in urls:
                    if not url:
                        continue
                    content = await self._llmToolGetUrlContent(extraData=extraData, url=url, parse_to_markdown=True)
                    if content and content[0] != "{":
                        # Check that there is any result and it isn't json
                        return {"url": url, "content": content}
                    else:
                        logger.warning(f"Failed to fetch content from {url}: {content}")
            except Exception as e:
                logger.exception(e)
                return None
            return None

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
                urlContentList: List[Dict[str, Any]] = []

                for group in searchResult["groups"]:
                    for doc in group:
                        urlContentList.append(
                            {
                                "url": doc["url"],
                                "description": doc.get("extendedText", "") + "\n" + "\n".join(doc["passages"]),
                                "fetcher": asyncio.create_task(
                                    fetchUrlContent([doc["url"], doc.get("savedCopyUrl", None)])
                                ),
                            }
                        )

                logger.debug(f"Fetching {len(urlContentList)} pages: {urlContentList}")
                for i, contentDict in enumerate(urlContentList):
                    try:
                        pageContent = await contentDict["fetcher"]
                        logger.debug(f"Fetched {i + 1}/{len(urlContentList)} pages: {pageContent}")
                        if pageContent is None:
                            ret["pages"].append({"url": contentDict["url"], "description": contentDict["description"]})
                        else:
                            ret["pages"].append(pageContent)

                    except Exception as e:
                        logger.error(f"Error during fetching content of {doc["url"]}: {e}")
                        logger.exception(e)
                        ret["pages"].append({"url": contentDict["url"], "description": contentDict["description"]})

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
        *,
        url: str,
        parse_to_markdown: bool = True,
        max_size: int = 10240,
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
            max_size: Max size returned, will be condensed via LLM if page is bigger
            **kwargs: Additional keyword arguments (unused)

        Returns:
            str: The content from the URL as a string, or a JSON error object
                 if the request fails
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("ensuredMessage should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError(
                f"ensuredMessage should be instance of EnsuredMessage but got {type(ensuredMessage).__name__}"
            )

        condensedCacheKey = {"url": url, "max_size": max_size}
        content = await self.urlContentCondensedCache.get(condensedCacheKey, self.urlContentCacheTTL)
        if content is not None:
            return content

        try:
            contentDict = await self.urlContentCache.get(url, self.urlContentCacheTTL)
            if contentDict is None:
                contentDict = await self._downloadUrl(url)
                if not contentDict.get("done", False):
                    # If done is not True, then it's some error, return it
                    return utils.jsonDumps(contentDict)
                contentType = contentDict["contentType"]
                if not contentType.startswith("text/"):
                    logger.warning(f"getUrl: content type of '{url}' is {contentType}")
                    return utils.jsonDumps({"done": False, "error": f"Content is not text, but {contentType}"})

                contentDict.pop("done", None)

                await self.urlContentCache.set(url, contentDict)

            content = contentDict["content"]
            contentType = contentDict["contentType"]

            if parse_to_markdown and "html" in contentType:
                # TODO: think about caching it as well. Or not
                # Parse to Markdown only if it's HTML
                content = html_to_markdown.convert(
                    content,
                    options=html_to_markdown.ConversionOptions(
                        extract_metadata=False,
                        strip_tags={"svg", "img"},
                    ),
                )

            if len(content) >= max_size:
                logger.debug(f"Content length is {len(content)} > {max_size}, condensing...")
                chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
                prompt = [
                    ModelMessage(
                        role="system",
                        content="Сделай максимально подробный пересказ этого документа. "
                        "Сохраняй язык оригинала (не переводи),"
                        " ответ так же давай на языке документа (не этого завпроса). "
                        "Включи все идеи, аргументы и факты. "
                        "Структура пересказа должна соответствовать структуре"
                        " исходного текста (разделы, подразделы). "
                        "Пересказывай исключительно на языке исходного текста.",
                    ),
                    ModelMessage(role="user", content=content),
                ]
                promptDump = "\n".join([f"\t{repr(v)}" for v in prompt])
                logger.debug(f"Will condense \n{promptDump}")
                mlRet = await self.llmService.generateText(
                    prompt=prompt,
                    chatId=ensuredMessage.recipient.id,
                    chatSettings=chatSettings,
                    llmManager=self.llmManager,
                    modelKey=ChatSettingsKey.CHAT_MODEL,
                    fallbackKey=ChatSettingsKey.CONDENSING_MODEL,
                )
                logger.debug(f"Condensing result: {mlRet}, len is {len(mlRet.resultText)}")
                if mlRet.status == ModelResultStatus.FINAL and mlRet.resultText:
                    content = mlRet.resultText
                    await self.urlContentCondensedCache.set(condensedCacheKey, content)

            return content

        except Exception as e:
            logger.error(f"Error getting content from {url}: {e}")
            return utils.jsonDumps({"done": False, "error": str(e)})

    async def _downloadUrl(self, url: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(60),  # Set Timeout to 1 minute for everything
                follow_redirects=True,
                max_redirects=5,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MyWebScraper/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru,en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate",
                    # "Connection": "keep-alive",
                    # TODO: add proxy support via config
                },
            ) as client:
                # response: requests.Response = requests.get(url, timeout=(120.0, 120.0))
                response = await client.get(url)
                await response.aread()

                if response.status_code < 200 or response.status_code >= 300:
                    return {
                        "done": False,
                        "error": f"Request failed with status {response.status_code}: {response.reason_phrase}",
                    }
                contentType = response.headers.get("Content-Type")
                if contentType is None:
                    contentType = "test/html"
                return {
                    "done": True,
                    "content": response.text,
                    "contentType": contentType,
                }
        except Exception as e:
            logger.error(f"Error getting content from {url}: {e}")
            return {
                "done": False,
                "error": str(e),
            }

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

    @commandHandlerV2(
        commands=("web_search",),
        shortDescription="<query> - Search Web for given query using Yandex",
        helpMessage=" `<query>`: Поискать в интернете используя Yandex Search API",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def web_search(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
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
        if not args:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать запрос для поиска.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        searchQuery = args

        chatId = ensuredMessage.recipient.id
        chatSettings = self.getChatSettings(chatId=chatId)
        # NOTE: We use llm's ratelimiter here, probably need to move it to more common place
        await self.llmService.rateLimit(chatId, chatSettings)

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
