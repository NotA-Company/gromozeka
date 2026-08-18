"""Stats handler for Gromozeka bot - displays usage statistics.

Provides /stats and /stats_web commands for querying and displaying
aggregated usage statistics (messages, commands, tools, LLM usage).
Only active when [stats] enabled = true in config.
"""

import datetime
import json
import logging
import time
from typing import Optional, TypedDict

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
from internal.bot.models.ensured_message import ChatType
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from internal.services.queue_service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from internal.services.stats import StatsAggregationService
from lib.rate_limiter import RateLimiterManager
from lib.stats import PeriodArg, StatsAnalyzer, computePeriodRange, mapPeriodArgToPeriodType
from lib.stats.stats_pages import (
    ChatListEntry,
    CommandsSectionData,
    LlmSectionData,
    MessagesSectionData,
    StatsCliError,
    StatsCliErrorReason,
    StatsPayload,
    SttSectionData,
    ToolsSectionData,
    runCliCommand,
)

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class StatsUsageError(Exception):
    """Exception raised when stats command arguments are invalid.

    Used to signal parse errors that should trigger usage text display.
    """

    def __init__(self, reason: str):
        """Initialize the usage error.

        Args:
            reason: One-line error description (prepended to usage text).
        """
        self.reason = reason
        super().__init__(reason)


class ParsedStatsArgs(TypedDict):
    """Parsed stats command arguments.

    Attributes:
        help: Whether help was requested.
        chatId: Optional chat ID for private scope drill-down.
        period: Period argument (1d, 7d, 30d, all).
        section: Section to display (messages, commands, tools, llm).
        user: Optional user ID filter.
        web: Whether web mode is enabled.
    """

    help: bool
    chatId: Optional[int]
    period: str
    section: str
    user: Optional[int]
    web: bool


class StatsHandler(BaseBotHandler):
    """Handler for statistics display commands.

    Provides /stats and /stats_web commands for querying aggregated
    statistics across messages, commands, tools, and LLM usage.
    Only registered when [stats] enabled = true in configuration.

    Attributes:
        statsAggregationService: Singleton service for accessing stats storage.
    """

    # Maximum output length to avoid message splitting
    _MAX_OUTPUT_LENGTH = 2500

    # Help text constants (deduplicated from three copies in the code)
    _USAGE_TEXT = (
        "Показать статистику использования бота.\n"
        "\n"
        "Аргументы:\n"
        "  help           - показать эту справку\n"
        "  chatId         - ID чата для показа статистики (только в личке)\n"
        "\n"
        "Опции:\n"
        "  --period=...   - период: 1d, 7d (по умолчанию), 30d, all\n"
        "  --section=...  - раздел: messages (по умолчанию), commands, tools, llm\n"
        "  --user=<id>    - показать статистику только для пользователя с ID\n"
        "  --web          - сгенерировать веб-страницу (если включено оператором)\n"
        "\n"
        "Примеры:\n"
        "  /stats                    - статистика за 7 дней для текущего чата\n"
        "  /stats --period=30d       - статистика за 30 дней\n"
        "  /stats --section=llm      - статистика использования LLM\n"
        "  /stats --user=12345       - статистика пользователя\n"
        "  /stats_web                - псевдоним для /stats --web"
    )

    _HELP_TEXT = (
        _USAGE_TEXT
        + "\n"
        + "\n"
        + "Примечания:\n"
        + "  --section=llm показывает статистику запросов LLM (на уровне чата, не пользователя).\n"
        + "  Для периодов 7d и 30d включается частичный текущий день (8/31 бакетов)."
    )

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """Initialize stats handler with dependencies.

        Args:
            configManager: Configuration manager for stats settings.
            database: Database wrapper.
            botProvider: Which bot platform this handler runs on.

        Raises:
            RuntimeError: If stats integration is disabled or stats-pages config is invalid.
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)

        statsConfig = configManager.getStatsConfig()
        if not statsConfig.get("enabled", False):
            logger.error("Stats integration is not enabled")
            raise RuntimeError("Stats integration is not enabled, cannot load StatsHandler")

        self.statsAggregationService = StatsAggregationService.getInstance()
        # botProvider is set by BaseBotHandler.__init__ (line 159)

        # D10: Validate stats-pages config when enabled
        statsPagesConfig = configManager.getStatsPagesConfig()
        self._statsPagesEnabled = statsPagesConfig.get("enabled", False)

        if self._statsPagesEnabled:
            # Validate base-url (kebab-case for TOML, must be non-empty string)
            baseUrl = statsPagesConfig.get("base-url")
            if not baseUrl or not isinstance(baseUrl, str) or not baseUrl.strip():
                raise RuntimeError("[stats-pages] base-url must be a non-empty string when enabled")

            # Validate generate-command (must be non-empty list[str] of non-empty strings)
            generateCommand = statsPagesConfig.get("generate-command")
            if (
                not generateCommand
                or not isinstance(generateCommand, list)
                or len(generateCommand) == 0
                or not all(isinstance(item, str) and item.strip() for item in generateCommand)
            ):
                raise RuntimeError(
                    "[stats-pages] generate-command must be a non-empty list[str] of non-empty strings when enabled"
                )

            # Validate delete-command (must be non-empty list[str] of non-empty strings)
            deleteCommand = statsPagesConfig.get("delete-command")
            if (
                not deleteCommand
                or not isinstance(deleteCommand, list)
                or len(deleteCommand) == 0
                or not all(isinstance(item, str) and item.strip() for item in deleteCommand)
            ):
                raise RuntimeError(
                    "[stats-pages] delete-command must be a non-empty list[str] of non-empty strings when enabled"
                )

            # Validate ttl-hours is positive int
            ttlHours = statsPagesConfig.get("ttl-hours", 24)
            if not isinstance(ttlHours, int) or ttlHours <= 0:
                raise RuntimeError("[stats-pages] ttl-hours must be a positive integer when enabled")

            # Cache validated config values (already lists from above validation)
            self._statsPagesBaseUrl = baseUrl.strip()
            self._statsPagesTtlHours = ttlHours
            self._statsPagesGenerateCommand = generateCommand
            self._statsPagesDeleteCommand = deleteCommand
            self._statsPagesRatelimiterQueue = statsPagesConfig.get("ratelimiter-queue", "stats-pages")

            # D14: Register cleanup handler
            QueueService.getInstance().registerDelayedTaskHandler(
                DelayedTaskFunction.STATS_PAGES_CLEANUP, self._dtStatsPagesCleanup
            )

    @commandHandlerV2(
        commands=("stats", "stats_web"),
        shortDescription="[help|chatId] [--period=...] [--section=...] [--user=<id>] [--web] - Statistics",
        helpMessage=_HELP_TEXT,
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def statsCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the ``/stats`` slash command (and ``/stats_web`` alias).

        Args:
            ensuredMessage: The originating user message.
            command: The command name (``"stats"`` or ``"stats_web"``).
            args: Raw argument string after the command.
            updateObj: Raw update object from the platform (unused).
            typingManager: Optional typing indicator manager.
        """
        # Apply ALLOW_SHOW_STATS gate for group/channel chats only
        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
            if not chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS].toBool():
                await self.sendMessage(
                    ensuredMessage,
                    messageText=(
                        "⚠ Показ статистики отключён в этом чате. Админ может включить "
                        "настройку «Показывать статистику чата»."
                    ),
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return

        # Parse arguments using argparse-style grammar
        try:
            parsedArgs = self._parseStatsArgs(args, command == "stats_web")
        except StatsUsageError as e:
            # Send usage reply with error reason
            usageReply = f"❌ {e.reason}\n\n{self._USAGE_TEXT}"
            await self.sendMessage(
                ensuredMessage,
                messageText=usageReply,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Validate that --user is not combined with --section=llm
        # (LLM statistics are chat-level, not per-user)
        # This validation must happen BEFORE the try/except around _buildStatsReply
        # so that StatsUsageError is caught by the usage reply handler above
        if parsedArgs["section"] == "llm" and parsedArgs["user"] is not None:
            # Send usage reply directly (avoid raising exception that gets swallowed)
            usageReply = (
                "❌ --section=llm не поддерживает --user: LLM-статистика общая для чата, не по пользователям\n\n"
                + self._USAGE_TEXT
            )
            await self.sendMessage(
                ensuredMessage,
                messageText=usageReply,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Handle help
        if parsedArgs["help"]:
            await self.sendMessage(
                ensuredMessage,
                messageText=self._HELP_TEXT,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Determine scope and target chat
        chatType = ensuredMessage.recipient.chatType
        targetChatId: int
        userId: int = ensuredMessage.sender.id

        # Handle positional chatId (private scope only per D3)
        positionalChatIdUsed = parsedArgs["chatId"] is not None
        if parsedArgs["chatId"] is not None:
            if chatType != ChatType.PRIVATE:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="❌ Аргумент chatId можно использовать только в личном чате.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return
            # Verify membership
            userChats = await self.getUserChats(userId)
            chatIdsInScope = {chat["chat_id"] for chat in userChats}
            if parsedArgs["chatId"] not in chatIdsInScope:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="❌ Чат не найден среди ваших чатов.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return
            targetChatId = parsedArgs["chatId"]
        else:
            # Default to current chat
            targetChatId = ensuredMessage.recipient.id

        # Map period arg to period type and compute range
        periodArg = parsedArgs["period"]
        periodType = mapPeriodArgToPeriodType(periodArg)
        periodStartFrom, periodStartTo = computePeriodRange(periodArg)

        # Handle web mode (D10/D11/D13/D14/D15)
        if parsedArgs["web"]:
            if not self._statsPagesEnabled:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=(
                        "⚠ Генерация веб-страниц отключена. Спросите оператора о настройке " "секции [stats-pages]."
                    ),
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return

            # D15: Wrap entire web-tier invocation so nothing escapes statsCommand
            try:
                await self._handleWebMode(
                    ensuredMessage=ensuredMessage,
                    targetChatId=targetChatId,
                    chatType=chatType,
                    userId=userId,
                    periodArg=periodArg,
                    section=parsedArgs["section"],
                    periodType=periodType,
                    periodStartFrom=periodStartFrom,
                    periodStartTo=periodStartTo,
                    filterUserId=parsedArgs["user"],
                    positionalChatIdUsed=positionalChatIdUsed,
                    typingManager=typingManager,
                )
            except Exception as e:
                logger.exception(f"Web mode failed for chat {targetChatId}: {e}")
                # D15: Always send brief + failure note, never let exception escape
                # Brief was already sent by _handleWebMode (rate-limit check or _buildStatsReply)
                await self.sendMessage(
                    ensuredMessage,
                    messageText="⚠ Генерация веб-страницы не удалась.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
            return

        # Query and display stats
        try:
            messageText = await self._buildStatsReply(
                targetChatId=targetChatId,
                chatType=chatType,
                userId=userId,
                section=parsedArgs["section"],
                periodArg=periodArg,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                filterUserId=parsedArgs["user"],
                positionalChatIdUsed=positionalChatIdUsed,
            )
        except Exception:
            logger.exception(f"Stats query failed for chat {targetChatId}")
            await self.sendMessage(
                ensuredMessage,
                messageText="❌ Ошибка при запросе статистики.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        await self.sendMessage(
            ensuredMessage,
            messageText=messageText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            typingManager=typingManager,
        )

    def _parseStatsArgs(self, args: str, forceWeb: bool = False) -> ParsedStatsArgs:
        """Parse stats command arguments using argparse-like grammar.

        Args:
            args: Raw argument string.
            forceWeb: Whether web mode is forced (from /stats_web alias).

        Returns:
            Parsed arguments dict with keys: help, chatId, period, section, user, web.

        Raises:
            StatsUsageError: If arguments are invalid (unknown option, bad value, etc.).
        """
        if not args.strip():
            # No args - defaults
            return {
                "help": False,
                "chatId": None,
                "period": PeriodArg.SEVEN_DAYS,
                "section": "messages",
                "user": None,
                "web": forceWeb,
            }

        # Split into tokens
        tokens = args.split()

        # Positional arguments (at most one: help OR chatId)
        positional: list[str] = []
        options: dict[str, Optional[str]] = {}

        # Parse tokens
        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Token starting with -- is an option
            if token.startswith("--"):
                optionName = token[2:]
                if "=" in optionName:
                    # --opt=value form
                    name, value = optionName.split("=", 1)
                    options[name] = value
                else:
                    # --opt value form - peek next token
                    # Special case: web is a valueless flag
                    if optionName == "web":
                        options[optionName] = ""
                    elif i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                        options[optionName] = tokens[i + 1]
                        i += 1
                    else:
                        # Flag without value (boolean)
                        options[optionName] = ""
                i += 1
            elif token == "help":
                positional.append("help")
                i += 1
            elif token.startswith("-") and token[1:].isdigit():
                # Negative number - treat as positional chatId (group ids are negative)
                positional.append(token)
                i += 1
            elif token.startswith("-"):
                # Unknown short option
                raise StatsUsageError(f"Неизвестная опция: {token}")
            else:
                # Other token - try to parse as chatId
                try:
                    int(token)
                    positional.append(token)
                except ValueError:
                    raise StatsUsageError(f"Неизвестный аргумент: {token}")
                i += 1

        # Validate positionals - at most one, and it's either help or chatId
        if len(positional) > 1:
            raise StatsUsageError("Укажите только один позиционный аргумент: help или chatId")
        if len(positional) == 1:
            if positional[0] == "help" and len(options) > 0:
                raise StatsUsageError("help не может сочетаться с другими аргументами")
            if positional[0] != "help":
                # Token already validated as int at line 464, so this conversion cannot fail
                chatId = int(positional[0])
            else:
                chatId = None
        else:
            chatId = None

        # Whitelist known options
        knownOptions = {"period", "section", "user", "web"}
        if not set(options.keys()).issubset(knownOptions):
            unknownOptions = set(options.keys()) - knownOptions
            raise StatsUsageError(f"Неизвестные опции: {', '.join(unknownOptions)}")

        # Parse options with defaults and validation
        period = options.get("period", PeriodArg.SEVEN_DAYS)
        if period not in (PeriodArg.ONE_DAY, PeriodArg.SEVEN_DAYS, PeriodArg.THIRTY_DAYS, PeriodArg.ALL):
            raise StatsUsageError(f"Неверный период: {period}. Используйте 1d, 7d, 30d, или all")

        section = options.get("section", "messages")
        if section not in ("messages", "commands", "tools", "llm"):
            raise StatsUsageError(f"Неизвестный раздел: {section}. Используйте messages, commands, tools, или llm")

        user = None
        if "user" in options:
            userValue = options["user"]
            if userValue is None or userValue == "":
                raise StatsUsageError("--user требует значения, например: --user=12345")
            try:
                user = int(userValue) if userValue else None
            except (ValueError, TypeError):
                raise StatsUsageError(f"Неверный user ID: {userValue}")

        web = "web" in options or forceWeb

        return {
            "help": positional == ["help"],
            "chatId": chatId,
            "period": period,
            "section": section,
            "user": user,
            "web": web,
        }

    async def _buildStatsReply(
        self,
        targetChatId: int,
        chatType: ChatType,
        userId: int,
        section: str,
        periodArg: str,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        filterUserId: Optional[int],
        positionalChatIdUsed: bool = False,
    ) -> str:
        """Build the stats reply message.

        Args:
            targetChatId: Chat to show stats for.
            chatType: Type of the target chat.
            userId: Current user ID (for scope checks).
            section: Section to display.
            periodArg: Original period argument string (for header label).
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            filterUserId: Optional user ID filter for drill-down.
            positionalChatIdUsed: Whether a positional chatId was provided (triggers multi-section).

        Returns:
            Formatted markdown reply string.
        """
        # Scope: group → this chat only, private → this chat or member chat
        consumerFilter = {str(targetChatId)}

        # D7 drill-down depth: positional chatId → all four sections
        sectionsToRender: list[str]
        if positionalChatIdUsed:
            # Positional chatId: render all four sections
            sectionsToRender = ["messages", "commands", "tools", "llm"]
        elif filterUserId is not None:
            # --user filter: render sections that support user filtering
            sectionsToRender = ["messages", "commands", "tools"]
        else:
            # Default: single section
            sectionsToRender = [section]

        # Build reply
        lines: list[str] = []

        # Header
        periodLabel = {
            PeriodArg.ONE_DAY: "1d",
            PeriodArg.SEVEN_DAYS: "7d",
            PeriodArg.THIRTY_DAYS: "30d",
            PeriodArg.ALL: "всё время",
        }.get(periodArg, periodArg)

        chatIdentifier = f"#{targetChatId}"
        lines.append(f"📊 Stats — {periodLabel} (UTC) — {chatIdentifier}")

        # Build section views
        for renderSection in sectionsToRender:
            sectionView = await self._buildSectionView(
                targetChatId=targetChatId,
                section=renderSection,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                consumerFilter=consumerFilter,
                filterUserId=filterUserId,
            )
            lines.append(sectionView)
            if renderSection != sectionsToRender[-1]:
                lines.append("")  # Blank line between sections

        # In private scope, add chat list for default messages section (private ∧ no user filter)
        if chatType == ChatType.PRIVATE and section == "messages" and filterUserId is None:
            lines.append("")
            lines.append("Ваши чаты:")
            userChats = await self.getUserChats(userId)
            # Sort by messages_count descending, top 10
            userChats.sort(key=lambda c: c.get("messages_count", 0), reverse=True)
            for chat in userChats[:10]:
                chatId = chat["chat_id"]
                title = chat["title"] or f"#{chatId}"
                msgCount = chat.get("messages_count", 0)
                lines.append(f"  #{chatId} {title} — {msgCount}")
            if len(userChats) > 10:
                lines.append(f"  … и ещё {len(userChats) - 10} чатов")

        # Footer
        lines.append("")
        lines.append("/stats help — полная справка")

        # Join and check length
        replyText = "\n".join(lines)
        if len(replyText) > self._MAX_OUTPUT_LENGTH:
            # Truncate to whole lines only
            truncatedLines = []
            currentLength = 0
            for line in lines:
                lineLength = len(line) + 1  # +1 for newline
                if currentLength + lineLength <= self._MAX_OUTPUT_LENGTH:
                    truncatedLines.append(line)
                    currentLength += lineLength
                else:
                    break
            replyText = "\n".join(truncatedLines)
            if replyText:
                replyText += "\n… (вывод ограничен)"

        return replyText

    async def _buildSectionView(
        self,
        targetChatId: int,
        section: str,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> str:
        """Build the view for a specific stats section.

        Args:
            targetChatId: Chat to show stats for.
            section: Section to display.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Formatted section view string.
        """
        # Section builders
        if section == "messages":
            return await self._buildMessagesSection(
                targetChatId=targetChatId,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                consumerFilter=consumerFilter,
                filterUserId=filterUserId,
            )
        elif section == "commands":
            return await self._buildCommandsSection(
                targetChatId=targetChatId,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                consumerFilter=consumerFilter,
                filterUserId=filterUserId,
            )
        elif section == "tools":
            return await self._buildToolsSection(
                targetChatId=targetChatId,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                consumerFilter=consumerFilter,
                filterUserId=filterUserId,
            )
        elif section == "llm":
            return await self._buildLlmSection(
                targetChatId=targetChatId,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                consumerFilter=consumerFilter,
                filterUserId=filterUserId,
            )
        else:
            # This should be unreachable because section is validated in _parseStatsArgs,
            # but we keep it for type safety and defensive programming.
            return f"❌ Неизвестный раздел: {section}"

    async def _buildMessagesSection(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> str:
        """Build the messages section view.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Formatted messages section string.
        """
        storage = self.statsAggregationService.getQueryStorage("message")
        rows = await storage.query(
            eventType="message",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        # Apply user filter if specified
        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        # Direction breakdown: sent=True (bot), sent=False (users), absent (history)
        userCount = analyzer.filterByLabel("sent", "False").sumMetric("message_count")
        botCount = analyzer.filterByLabel("sent", "True").sumMetric("message_count")

        # History count = rows without sent label
        analyzerAll = analyzer  # All rows (including history)
        totalMessageCount = analyzerAll.sumMetric("message_count")
        historyCount = totalMessageCount - userCount - botCount

        # Top users (by message count)
        topUsers = analyzerAll.filterByLabel("sent", "False").topN("user_id", "message_count", 3)

        # Build lines
        lines: list[str] = [f"Messages: {int(totalMessageCount)}"]
        lines.append(f"  users {int(userCount)} / bot {int(botCount)} / history {int(historyCount)}")

        if topUsers:
            topUserNames = []
            for userIdStr, count in topUsers:
                try:
                    userIdInt = int(userIdStr)
                except (ValueError, TypeError):
                    userIdInt = 0  # Fallback for invalid user IDs
                userName = await self._resolveUserName(targetChatId, userIdInt)
                topUserNames.append(f"{userName} {int(count)}")
            lines.append(f"  Top: {' · '.join(topUserNames)}")

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполные")

        return "\n".join(lines)

    async def _buildCommandsSection(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> str:
        """Build the commands section view.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Formatted commands section string.
        """
        storage = self.statsAggregationService.getQueryStorage("command")
        rows = await storage.query(
            eventType="command",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        totalCommands = analyzer.sumMetric("command_count")
        errorCommands = analyzer.sumMetric("is_error")

        topCommands = analyzer.topN("commandName", "command_count", 3)

        lines: list[str] = [f"Commands: {int(totalCommands)}"]
        if errorCommands > 0:
            lines.append(f"  errors: {int(errorCommands)}")
        if topCommands:
            topCmdNames = []
            for cmdName, count in topCommands:
                topCmdNames.append(f"{cmdName} {int(count)}")
            lines.append(f"  Top: {' · '.join(topCmdNames)}")

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполные")

        return "\n".join(lines)

    async def _buildToolsSection(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> str:
        """Build the tools section view.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Formatted tools section string.
        """
        storage = self.statsAggregationService.getQueryStorage("llm_tool_call")
        rows = await storage.query(
            eventType="llm_tool_call",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        totalCalls = analyzer.sumMetric("tool_call_count")
        errorCalls = analyzer.sumMetric("is_error")
        avgElapsed = analyzer.average("elapsed_time", "tool_call_count")

        topTools = analyzer.topN("toolName", "tool_call_count", 3)

        lines: list[str] = [f"Tools: {int(totalCalls)}"]
        if errorCalls > 0:
            lines.append(f"  errors: {int(errorCalls)}")
        if avgElapsed > 0:
            lines.append(f"  avg time: {avgElapsed:.2f}s")
        if topTools:
            topToolNames = []
            for toolName, count in topTools:
                topToolNames.append(f"{toolName} {int(count)}")
            lines.append(f"  Top: {' · '.join(topToolNames)}")

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполные")

        return "\n".join(lines)

    async def _buildLlmSection(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> str:
        """Build the LLM section view.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down (ignored for llm_request).

        Returns:
            Formatted LLM section string.
        """
        # Note: llm_request events don't carry user_id, so filterUserId is ignored for this section

        storage = self.statsAggregationService.getQueryStorage("llm_request")
        rows = await storage.query(
            eventType="llm_request",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        totalRequests = analyzer.sumMetric("request_count")
        errorRequests = analyzer.sumMetric("is_error")
        totalInputTokens = analyzer.sumMetric("input_tokens")
        totalOutputTokens = analyzer.sumMetric("output_tokens")

        avgElapsed = analyzer.average("elapsed_time", "request_count")

        topModels = analyzer.topN("modelName", "request_count", 3)

        lines: list[str] = [f"LLM: {int(totalRequests)} requests"]
        if errorRequests > 0:
            lines.append(f"  errors: {int(errorRequests)}")
        lines.append(f"  tokens: in {int(totalInputTokens)} / out {int(totalOutputTokens)}")
        if avgElapsed > 0:
            lines.append(f"  avg time: {avgElapsed:.2f}s")
        if topModels:
            topModelNames = []
            for modelName, count in topModels:
                topModelNames.append(f"{modelName} {int(count)}")
            lines.append(f"  Top models: {' · '.join(topModelNames)}")

        # Annotation for user-level filtering
        if filterUserId is not None:
            lines.append("  (на уровне чата, не пользователя)")

        # STT stats (stt_request event type)
        sttStorage = self.statsAggregationService.getQueryStorage("stt_request")
        sttRows = await sttStorage.query(
            eventType="stt_request",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the STT limit
        sttPossiblyIncomplete = len(sttRows) == 10000

        if sttRows:
            sttAnalyzer = StatsAnalyzer(sttRows)
            sttAnalyzer = sttAnalyzer.filterByLabelIn("consumer", consumerFilter)

            totalSttRequests = sttAnalyzer.sumMetric("request_count")
            errorSttRequests = sttAnalyzer.sumMetric("is_error")
            totalAudioDurationMs = sttAnalyzer.sumMetric("audio_duration_ms")
            totalSttElapsedTime = sttAnalyzer.sumMetric("elapsed_time")

            lines.append(f"  STT: {int(totalSttRequests)} запросов")
            if errorSttRequests > 0:
                lines.append(f"    errors: {int(errorSttRequests)}")
            if totalAudioDurationMs > 0:
                audioDurationSecs = totalAudioDurationMs / 1000.0
                lines.append(f"    audio: {audioDurationSecs:.1f}s")
            if totalSttRequests > 0:
                avgSttTime = totalSttElapsedTime / totalSttRequests
                lines.append(f"    avg time: {avgSttTime:.2f}s")

            # D5 honesty line for STT
            if sttPossiblyIncomplete:
                lines.append("    ⚠ результаты возможно неполные")

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполные")

        return "\n".join(lines)

    async def _resolveUserName(self, chatId: int, userId: int) -> str:
        """Resolve a user ID to a display name.

        Args:
            chatId: Chat to look up the user in.
            userId: User ID to resolve.

        Returns:
            Display name (username or full_name or raw ID as fallback).
        """
        try:
            chatUser = await self.cache.getChatUser(chatId=chatId, userId=userId)
            if chatUser:
                username = chatUser.get("username")
                fullName = chatUser.get("full_name")
                if username:
                    return f"@{username}"
                elif fullName:
                    return fullName
        except Exception:
            logger.debug(f"Failed to resolve user {userId} in chat {chatId}")
        # Fallback to raw ID
        return str(userId)

    async def _buildStatsPayload(
        self,
        targetChatId: int,
        chatType: ChatType,
        userId: int,
        periodArg: str,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        filterUserId: Optional[int],
        positionalChatIdUsed: bool = False,
    ) -> StatsPayload:
        """Build the stats payload for web page generation.

        Args:
            targetChatId: Chat to show stats for.
            chatType: Type of the target chat.
            userId: Current user ID (for scope checks).
            periodArg: Original period argument string (for header label).
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            filterUserId: Optional user ID filter for drill-down.
            positionalChatIdUsed: Whether a positional chatId was provided.

        Returns:
            StatsPayload dict with all required meta fields and sections.
        """
        # Scope: group → this chat only, private → this chat or member chat
        consumerFilter = {str(targetChatId)}

        # Build sections data for all four sections
        sectionsData: dict[str, MessagesSectionData | CommandsSectionData | ToolsSectionData | LlmSectionData] = {}
        sectionsData["messages"] = await self._buildMessagesSectionData(
            targetChatId=targetChatId,
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            consumerFilter=consumerFilter,
            filterUserId=filterUserId,
        )
        sectionsData["commands"] = await self._buildCommandsSectionData(
            targetChatId=targetChatId,
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            consumerFilter=consumerFilter,
            filterUserId=filterUserId,
        )
        sectionsData["tools"] = await self._buildToolsSectionData(
            targetChatId=targetChatId,
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            consumerFilter=consumerFilter,
            filterUserId=filterUserId,
        )
        sectionsData["llm"] = await self._buildLlmSectionData(
            targetChatId=targetChatId,
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            consumerFilter=consumerFilter,
        )

        # Chat list for private scope (match reply path condition)
        chatList: list[ChatListEntry] = []
        if chatType == ChatType.PRIVATE and filterUserId is None:
            userChats = await self.getUserChats(userId)
            # Sort by messages_count descending, top 10
            userChats.sort(key=lambda c: c.get("messages_count", 0), reverse=True)
            for chat in userChats[:10]:
                chatList.append(
                    {
                        "chatId": chat["chat_id"],
                        "title": chat["title"] or f"#{chat['chat_id']}",
                        "messagesCount": chat.get("messages_count", 0),
                    }
                )

        # Resolve chat title
        chatTitle = str(targetChatId)
        if chatType == ChatType.PRIVATE and not positionalChatIdUsed:
            # Current private chat
            chatUser = await self.cache.getChatUser(chatId=targetChatId, userId=userId)
            if chatUser:
                chatTitle = chatUser.get("full_name") or chatTitle
        elif chatType != ChatType.PRIVATE:
            # Group or channel - try to get title from cache or database
            try:
                chatInfo = await self.cache.getChatInfo(chatId=targetChatId)
                if chatInfo:
                    chatTitle = chatInfo.get("title") or chatTitle
            except Exception:
                pass

        # Build payload (FIX 7: use chatType.value instead of ternary)
        payload: StatsPayload = {
            "userId": str(userId),
            "chatId": str(targetChatId),
            "chatTitle": chatTitle,
            "chatType": chatType.value,  # FIX 7: Use StrEnum value ("private"/"group"/"channel")
            "platform": self.botProvider.value,
            "period": periodArg,
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sections": sectionsData,  # type: ignore[assignment]  # MessagesSectionData etc. are dict[str, Any]
        }

        if chatList:
            payload["chatList"] = chatList  # type: ignore[assignment]  # ChatListEntry is dict[str, Any]

        return payload

    async def _buildMessagesSectionData(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> MessagesSectionData:
        """Build structured data for the messages section.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Structured messages section data.
        """
        storage = self.statsAggregationService.getQueryStorage("message")
        rows = await storage.query(
            eventType="message",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit (FIX 5: add to payload)
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        # Apply user filter if specified
        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        # Direction breakdown
        userCount = analyzer.filterByLabel("sent", "False").sumMetric("message_count")
        botCount = analyzer.filterByLabel("sent", "True").sumMetric("message_count")

        # History count
        analyzerAll = analyzer
        totalMessageCount = analyzerAll.sumMetric("message_count")
        historyCount = totalMessageCount - userCount - botCount

        # Total length
        totalLength = analyzerAll.sumMetric("text_length")
        avgLength = totalLength / max(totalMessageCount, 1)  # Compute average text length per message

        # Top users (by message count)
        topUsers = analyzerAll.filterByLabel("sent", "False").topN("user_id", "message_count", 3)

        # Top message types
        topTypes = analyzerAll.topN("message_type", "message_count", 3)

        return {
            "totalMessages": int(totalMessageCount),
            "totalLength": int(totalLength),
            "userMessages": int(userCount),
            "botMessages": int(botCount),
            "historyMessages": int(historyCount),
            "avgLength": float(avgLength),
            "topUsers": [[userIdStr, int(count)] for userIdStr, count in topUsers],
            "topTypes": [[msgType, int(count)] for msgType, count in topTypes],
            "possiblyIncomplete": possiblyIncomplete,  # FIX 5: add honesty flag
        }

    async def _buildCommandsSectionData(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> CommandsSectionData:
        """Build structured data for the commands section.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Structured commands section data.
        """
        storage = self.statsAggregationService.getQueryStorage("command")
        rows = await storage.query(
            eventType="command",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit (FIX 5: add to payload)
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        totalCommands = analyzer.sumMetric("command_count")
        errorCommands = analyzer.sumMetric("is_error")
        totalElapsed = analyzer.sumMetric("elapsed_time")
        avgElapsed = (
            totalElapsed / max(totalCommands, 1) if totalCommands > 0 else 0.0
        )  # Compute average elapsed time per command

        topCommands = analyzer.topN("commandName", "command_count", 3)

        return {
            "totalCommands": int(totalCommands),
            "errorCommands": int(errorCommands),
            "totalElapsed": float(totalElapsed),
            "avgElapsed": float(avgElapsed),
            "topCommands": [[cmdName, int(count)] for cmdName, count in topCommands],
            "possiblyIncomplete": possiblyIncomplete,  # FIX 5: add honesty flag
        }

    async def _buildToolsSectionData(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
        filterUserId: Optional[int],
    ) -> ToolsSectionData:
        """Build structured data for the tools section.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.
            filterUserId: Optional user ID filter for drill-down.

        Returns:
            Structured tools section data.
        """
        storage = self.statsAggregationService.getQueryStorage("llm_tool_call")
        rows = await storage.query(
            eventType="llm_tool_call",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit (FIX 5: add to payload)
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        totalCalls = analyzer.sumMetric("tool_call_count")
        errorCalls = analyzer.sumMetric("is_error")
        totalElapsed = analyzer.sumMetric("elapsed_time")
        avgElapsed = (
            totalElapsed / max(totalCalls, 1) if totalCalls > 0 else 0.0
        )  # Compute average elapsed time per tool call

        topTools = analyzer.topN("toolName", "tool_call_count", 3)

        return {
            "totalCalls": int(totalCalls),
            "errorCalls": int(errorCalls),
            "totalElapsed": float(totalElapsed),
            "avgElapsed": float(avgElapsed),
            "topTools": [[toolName, int(count)] for toolName, count in topTools],
            "possiblyIncomplete": possiblyIncomplete,  # FIX 5: add honesty flag
        }

    async def _buildLlmSectionData(
        self,
        targetChatId: int,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        consumerFilter: set[str],
    ) -> LlmSectionData:
        """Build structured data for the LLM section.

        Args:
            targetChatId: Chat to show stats for.
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            consumerFilter: Consumer IDs to filter by.

        Returns:
            Structured LLM section data.
        """
        storage = self.statsAggregationService.getQueryStorage("llm_request")
        rows = await storage.query(
            eventType="llm_request",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        # D5 honesty line: check if we hit the limit (FIX 5: add to payload)
        possiblyIncomplete = len(rows) == 10000

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        totalRequests = analyzer.sumMetric("request_count")
        errorRequests = analyzer.sumMetric("is_error")
        totalInputTokens = analyzer.sumMetric("input_tokens")
        totalOutputTokens = analyzer.sumMetric("output_tokens")
        totalElapsed = analyzer.sumMetric("elapsed_time")
        avgElapsed = (
            totalElapsed / max(totalRequests, 1) if totalRequests > 0 else 0.0
        )  # Compute average elapsed time per LLM request

        topModels = analyzer.topN("modelName", "request_count", 3)
        topProviders = analyzer.topN("provider", "request_count", 3)

        # STT stats
        sttStorage = self.statsAggregationService.getQueryStorage("stt_request")
        sttRows = await sttStorage.query(
            eventType="stt_request",
            periodType=periodType,
            periodStartFrom=periodStartFrom,
            periodStartTo=periodStartTo,
            limit=10000,
        )

        sttData: SttSectionData | None = None
        if sttRows:
            sttAnalyzer = StatsAnalyzer(sttRows)
            sttAnalyzer = sttAnalyzer.filterByLabelIn("consumer", consumerFilter)

            # D5 honesty line: check if we hit the limit
            possiblyIncompleteStt = len(sttRows) == 10000

            totalSttRequests = sttAnalyzer.sumMetric("request_count")
            errorSttRequests = sttAnalyzer.sumMetric("is_error")
            totalAudioDurationMs = sttAnalyzer.sumMetric("audio_duration_ms")
            totalSttElapsedTime = sttAnalyzer.sumMetric("elapsed_time")
            avgSttTime = totalSttElapsedTime / max(totalSttRequests, 1) if totalSttRequests > 0 else 0.0

            sttData = {
                "totalRequests": int(totalSttRequests),
                "errorRequests": int(errorSttRequests),
                "totalAudioDuration": float(totalAudioDurationMs / 1000.0),
                "totalElapsed": float(totalSttElapsedTime),
                "avgElapsed": float(avgSttTime),
                "topProviders": [
                    [provider, int(count)] for provider, count in sttAnalyzer.topN("provider", "request_count", 3)
                ],
                "possiblyIncomplete": possiblyIncompleteStt,
            }

        result: LlmSectionData = {
            "totalRequests": int(totalRequests),
            "errorRequests": int(errorRequests),
            "inputTokens": int(totalInputTokens),
            "outputTokens": int(totalOutputTokens),
            "totalTokens": int(totalInputTokens + totalOutputTokens),
            "totalElapsed": float(totalElapsed),
            "avgElapsed": float(avgElapsed),
            "topModels": [[model, int(count)] for model, count in topModels],
            "topProviders": [[provider, int(count)] for provider, count in topProviders],
            "possiblyIncomplete": possiblyIncomplete,  # FIX 5: add honesty flag
        }

        if sttData is not None:
            result["stt"] = sttData

        return result

    async def _handleWebMode(
        self,
        ensuredMessage: EnsuredMessage,
        targetChatId: int,
        chatType: ChatType,
        userId: int,
        periodArg: str,
        section: str,
        periodType: str,
        periodStartFrom: Optional[str],
        periodStartTo: Optional[str],
        filterUserId: Optional[int],
        positionalChatIdUsed: bool,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle web mode: generate stats page via subprocess and send link.

        Args:
            ensuredMessage: The originating user message.
            targetChatId: Chat to show stats for.
            chatType: Type of the target chat.
            userId: Current user ID.
            periodArg: Original period argument string.
            section: Section to display (for chat brief).
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound.
            periodStartTo: ISO-8601 UTC end bound.
            filterUserId: Optional user ID filter.
            positionalChatIdUsed: Whether positional chatId was used.
            typingManager: Optional typing indicator manager.
        """
        # D13: Rate limit check FIRST
        # FIX 6: Key limiter on ISSUING chat (ensuredMessage.recipient.id), not target chat
        rateLimiterKey = f"stats-pages-{ensuredMessage.recipient.id}"
        limiterUnavailable = False
        maxRequests: int = 3
        windowSeconds: int = 3600
        used: int = 0
        try:
            rateStats = RateLimiterManager.getInstance().getStats(self._statsPagesRatelimiterQueue, key=rateLimiterKey)
            used = rateStats["requestsInWindow"]
            maxRequests = rateStats["maxRequests"]
            windowSeconds = rateStats.get("windowSeconds", 3600)  # FIX 6: read window unit from rateStats
        except RuntimeError:
            # Limiter unavailable (queue not registered) - build brief and note, then return
            limiterUnavailable = True
        except ValueError:
            # Never-used key (no requests yet for this chat) - treat as 0 used
            # FIX 6: Simplified - just set used=0, skip the comparison entirely (0 can't exceed positive limit)
            used = 0
            # Need maxRequests for the limit check - get queue level stats
            # Note: queue-name key is never populated by this handler (applyLimit uses per-chat keys),
            # so the hardcoded 3/3600 fallback is what first-requests actually compare against
            try:
                queueStats = RateLimiterManager.getInstance().getStats(self._statsPagesRatelimiterQueue, key=None)
                maxRequests = queueStats["maxRequests"]
                windowSeconds = queueStats.get("windowSeconds", 3600)  # FIX 6: read window unit from rateStats
            except (ValueError, KeyError):
                # Fallback if queue-level stats also fail (shouldn't happen with valid config)
                maxRequests = 3
                windowSeconds = 3600

        if limiterUnavailable:
            # Build brief reply when limiter is unavailable
            try:
                messageText = await self._buildStatsReply(
                    targetChatId=targetChatId,
                    chatType=chatType,
                    userId=userId,
                    section=section,
                    periodArg=periodArg,
                    periodType=periodType,
                    periodStartFrom=periodStartFrom,
                    periodStartTo=periodStartTo,
                    filterUserId=filterUserId,
                    positionalChatIdUsed=positionalChatIdUsed,
                )
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"{messageText}\n\n⚠ Лимитер генерации страниц недоступен.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
            except Exception:
                logger.exception(f"Stats query failed for chat {targetChatId}")
                await self.sendMessage(
                    ensuredMessage,
                    messageText="❌ Ошибка при запросе статистики.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
            return

        if used >= maxRequests:
            # Russian pluralization helper
            def formatRussianPlural(n: int, singular: str, paucal: str, plural: str) -> str:
                """Format number with correct Russian plural form."""
                if n == 1 or (n % 10 == 1 and n % 100 != 11):
                    return f"{n} {singular}"
                elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
                    return f"{n} {paucal}"
                else:
                    return f"{n} {plural}"

            windowHours = windowSeconds // 3600
            if windowHours >= 1:
                windowLabel = formatRussianPlural(windowHours, "час", "часа", "часов")
            else:
                windowLabel = formatRussianPlural(windowSeconds, "секунда", "секунды", "секунд")

            requestsLabel = formatRussianPlural(maxRequests, "запрос", "запроса", "запросов")

            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    f"⚠ Превышен лимит генерации страниц (попробуйте позже). "
                    f"Максимум: {requestsLabel} за {windowLabel}."
                ),
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Apply the rate limit (record the attempt)
        await RateLimiterManager.getInstance().applyLimit(self._statsPagesRatelimiterQueue, rateLimiterKey)

        # Build the in-chat reply first (D15: reply always wins)
        try:
            messageText = await self._buildStatsReply(
                targetChatId=targetChatId,
                chatType=chatType,
                userId=userId,
                section=section,
                periodArg=periodArg,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                filterUserId=filterUserId,
                positionalChatIdUsed=positionalChatIdUsed,
            )
        except Exception:
            logger.exception(f"Stats query failed for chat {targetChatId}")
            await self.sendMessage(
                ensuredMessage,
                messageText="❌ Ошибка при запросе статистики.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Build payload for subprocess
        try:
            payload = await self._buildStatsPayload(
                targetChatId=targetChatId,
                chatType=chatType,
                userId=userId,
                periodArg=periodArg,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                filterUserId=filterUserId,
                positionalChatIdUsed=positionalChatIdUsed,
            )
        except Exception:
            logger.exception(f"Stats payload build failed for chat {targetChatId}")
            # Brief was already built and sent above, just add failure note
            await self.sendMessage(
                ensuredMessage,
                messageText=f"{messageText}\n\n⚠ Генерация веб-страницы не удалась.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Resolve generate-command argv with substitutions
        placeholders = {
            "user_id": str(userId),
            "chat_id": str(targetChatId),
            "platform": self.botProvider.value,
        }

        try:
            argv = [arg.format_map(placeholders) for arg in self._statsPagesGenerateCommand]
        except (KeyError, AttributeError) as e:  # FIX 2: Catch AttributeError for non-str templates
            logger.warning("stats-pages generate-command contains unknown placeholder or non-str template: %s", e)
            # Fall back to in-chat reply with failure note
            await self.sendMessage(
                ensuredMessage,
                messageText=f"{messageText}\n\n⚠ Генерация веб-страницы не удалась (ошибка конфигурации).",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Invoke subprocess using the launcher
        try:
            returncode, stdout, stderr = await runCliCommand(
                argv=argv,
                stdinPayload=json.dumps(payload),
                timeoutSeconds=30.0,
            )
        except StatsCliError as e:
            if e.reason == StatsCliErrorReason.TIMEOUT:
                logger.warning("stats-pages generate timed out for chat %s", targetChatId)
                # Fall back to in-chat reply with failure note
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"{messageText}\n\n⚠ Генерация веб-страницы не удалась (тайм-аут).",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return
            else:
                # SPAWN or other error
                logger.warning("stats-pages generate failed for chat %s: %s", targetChatId, e.message)
                # Fall back to in-chat reply with failure note
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"{messageText}\n\n⚠ Генерация веб-страницы не удалась.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return

        if returncode is not None and returncode != 0:
            logger.warning(
                "stats-pages generate failed for chat %s: exit code %d, stderr: %s",
                targetChatId,
                returncode,
                stderr,
            )
            # Fall back to in-chat reply with failure note
            await self.sendMessage(
                ensuredMessage,
                messageText=f"{messageText}\n\n⚠ Генерация веб-страницы не удалась.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Parse stdout JSON
        try:
            result = json.loads(stdout)
            pageId = result["id"]
            url = result["url"]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("stats-pages generate returned invalid JSON for chat %s: %s", targetChatId, e)
            # Fall back to in-chat reply with failure note
            await self.sendMessage(
                ensuredMessage,
                messageText=f"{messageText}\n\n⚠ Генерация веб-страницы не удалась (неверный ответ).",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Compose full link
        fullLink = f"{self._statsPagesBaseUrl.rstrip('/')}/{url}"

        # D14: Schedule deletion task on SUCCESSFUL generation
        try:
            deleteCommand = [arg.format_map({"page_id": pageId}) for arg in self._statsPagesDeleteCommand]
            await QueueService.getInstance().addDelayedTask(
                delayedUntil=time.time() + self._statsPagesTtlHours * 3600,
                function=DelayedTaskFunction.STATS_PAGES_CLEANUP,
                kwargs={"pageId": pageId, "command": deleteCommand},
                skipDB=False,
            )
        except Exception as e:
            logger.warning("Failed to schedule deletion task for page %s: %s", pageId, e)
            # Accept orphaned page per R13, still deliver the link

        # Send reply with link
        await self.sendMessage(
            ensuredMessage,
            messageText=f"{messageText}\n\n📊 Страница: {fullLink}",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            typingManager=typingManager,
        )

    async def _dtStatsPagesCleanup(self, task: DelayedTask) -> None:
        """Handle delayed task for stats page cleanup (one-shot per-page deletion).

        Args:
            task: The delayed task to execute.
        """
        pageId = task.kwargs.get("pageId")
        command = task.kwargs.get("command")

        if not pageId or not command:
            logger.warning("stats-pages cleanup task missing pageId or command: %s", task.kwargs)
            return

        try:
            returncode, stdout, stderr = await runCliCommand(
                argv=command,
                timeoutSeconds=30.0,
            )
        except StatsCliError as e:
            if e.reason == StatsCliErrorReason.TIMEOUT:
                logger.warning("stats-pages delete timed out for page %s", pageId)
            else:
                logger.warning("stats-pages delete failed for page %s: %s", pageId, e.message)
            return

        if returncode is not None and returncode != 0:
            logger.warning(
                "stats-pages delete failed for page %s: exit code %d, stderr: %s",
                pageId,
                returncode,
                stderr,
            )
            return

        # Parse stdout JSON ({"deleted": 0|1})
        try:
            result = json.loads(stdout)
            deleted = result.get("deleted", 0)
            if deleted == 0:
                logger.info("stats-pages delete: page %s not found (already deleted)", pageId)
        except (json.JSONDecodeError, KeyError):
            logger.warning("stats-pages delete returned invalid JSON for page %s", pageId)
