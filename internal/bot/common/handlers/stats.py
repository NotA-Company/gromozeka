"""Stats handler for Gromozeka bot - displays usage statistics.

Provides /stats and /stats_web commands for querying and displaying
aggregated usage statistics (messages, commands, tools, LLM usage).
Only active when [stats] enabled = true in config.
"""

import logging
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
from internal.services.stats import StatsAggregationService
from lib.stats import PeriodArg, StatsAnalyzer, computePeriodRange, mapPeriodArgToPeriodType

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
        "  --web          - сгенерировать веб-страницу (пока отключено)\n"
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
            RuntimeError: If stats integration is disabled.
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)

        statsConfig = configManager.getStatsConfig()
        if not statsConfig.get("enabled", False):
            logger.error("Stats integration is not enabled")
            raise RuntimeError("Stats integration is not enabled, cannot load StatsHandler")

        self.statsAggregationService = StatsAggregationService.getInstance()

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

        # Handle web mode (interim disabled reply)
        if parsedArgs["web"]:
            statsPagesConfig = self.configManager.get("stats-pages", {})
            if not statsPagesConfig.get("enabled", False):
                await self.sendMessage(
                    ensuredMessage,
                    messageText=(
                        "⚠ Генерация веб-страниц отключена. Спросите оператора о настройке " "секции [stats-pages]."
                    ),
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return
            # Full web tier is Phase 3 - interim reply
            await self.sendMessage(
                ensuredMessage,
                messageText="⚠ Генерация веб-страниц временно отключена (функциональность в разработке).",
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
                # Token already validated as int at line 358, so this conversion cannot fail
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

        # In private scope, add chat list for default messages section
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
