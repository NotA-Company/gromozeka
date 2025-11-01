"""TODO"""

import asyncio
import logging
from typing import Any, Dict, Optional, Sequence

from telegram import Update
from telegram.ext import ContextTypes

import lib.utils as utils
import lib.yandex_search as ys
from internal.config.manager import ConfigManager
from internal.database.models import (
    MessageCategory,
)
from internal.database.wrapper import DatabaseWrapper
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
    EnsuredMessage,
    commandHandler,
)
from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class YandexSearchHandler(BaseBotHandler):
    """
    TODO
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        TODO
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
            cache=None,  # TODO: Do DB cache,
            cacheTTL=int(ysConfig.get("cache-ttl", 30)),
            useCache=True,
            rateLimitRequests=int(ysConfig.get("rate-limit-requests", 10)),
            rateLimitWindow=int(ysConfig.get("rate-limit-window", 60)),
        )
        self.yandexSearchDefaults = ysConfig.get("defaults", {})

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

    async def _llmToolWebSearch(
        self, extraData: Optional[Dict[str, Any]], query: str, enable_content_filter: bool = False, **kwargs
    ) -> str:
        """TODO"""
        try:
            contentFilter: ys.FamilyMode = (
                ys.FamilyMode.FAMILY_MODE_MODERATE if enable_content_filter else ys.FamilyMode.FAMILY_MODE_NONE
            )
            kwargs = {**self.yandexSearchDefaults, "familyMode": contentFilter}
            ret = await self.yandexSearchClient.search(query, **kwargs)
            if ret is None:
                return utils.jsonDumps({"done": False, "errorMessage": "Failed to perform web search"})

            # Drop useless things
            # TODO

            return utils.jsonDumps({**ret, "done": "error" not in ret})
        except Exception as e:
            logger.error(f"Error getting weather: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    def _formatSearchResult(self, searchResult: ys.SearchResponse) -> Sequence[str]:
        # First element is header, then each group as str
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

    @commandHandler(
        commands=("web_search",),
        shortDescription="<query> - Search Web for given query using Yandex",
        helpMessage=" `<query>`: Поискать в интернете используя Yandex Search API",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def web_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /web_search command
        TODO
        """
        logger.debug(f"Got /web_search command: {update}")
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

            # resp = await self._formatWeather(weatherData)
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
