"""Stats handler for Gromozeka bot - displays usage statistics.

Provides /stats and /stats_web commands for querying and displaying
aggregated usage statistics (messages, commands, tools, LLM usage).
Only active when [stats] enabled = true in config.
"""

import asyncio
import datetime
import json
import logging
import math
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
from lib.stats import StatsAnalyzer, computePeriodRange, mapPeriodArgToPeriodType
from lib.stats.stats_pages import (
    ChatListEntry,
    StatsCliError,
    StatsCliErrorReason,
    StatsPayload,
    runCliCommand,
)
from lib.stats.types import STATS_QUERY_ROW_LIMIT, StatsAggregateDict

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
        period: Period argument (Nh, Nd, Nm, all).
        section: Section to display (messages, commands, tools, llm, all).
        user: Optional user ID filter (numeric ID or @username string).
        web: Whether web mode is enabled.
    """

    help: bool
    chatId: Optional[int]
    period: str
    section: str
    user: Optional[str]
    web: bool


class StatsHandler(BaseBotHandler):
    """Handler for statistics display commands.

    Provides /stats and /stats_web commands for querying aggregated
    statistics across messages, commands, tools, and LLM usage.
    Only registered when [stats] enabled = true in configuration.

    Attributes:
        statsAggregationService: Singleton service for accessing stats storage.
    """

    _OUTPUT_CHUNK_LENGTH = 3000

    # Delay between consecutive chunk sends (seconds)
    _CHUNK_SEND_DELAY_SECONDS: float = 0.5

    # Help text constants (deduplicated from three copies in the code)
    _USAGE_TEXT = (
        "Показать статистику использования бота.\n"
        "\n"
        "Аргументы:\n"
        "  help           - показать эту справку\n"
        "  chatId         - ID чата для показа статистики (только в личке)\n"
        "\n"
        "Опции:\n"
        "  --period=...   - период: Nh (1-24 часов), Nd (1-31 дней), Nm (N>=1 месяцев),\n"
        "                  all (все время; по умолчанию 7d)\n"
        "  --section=...  - раздел: messages (по умолчанию), commands, tools, llm, all\n"
        "  --user=<id>    - показать статистику только для пользователя с ID или @username\n"
        "  --web          - сгенерировать веб-страницу (если включено оператором)\n"
        "\n"
        "Примеры:\n"
        "  /stats                    - статистика за 7 дней для текущего чата\n"
        "  /stats --period=30d       - статистика за 30 дней\n"
        "  /stats --section=llm      - статистика использования LLM\n"
        "  /stats --user=12345       - статистика пользователя\n"
        "  /stats --user=@john       - статистика пользователя @john\n"
        "  /stats_web                - псевдоним для /stats --web"
    )

    _HELP_TEXT = (
        _USAGE_TEXT
        + "\n"
        + "\n"
        + "Примечания:\n"
        + "  --section=llm показывает статистику запросов LLM (на уровне чата, не пользователя).\n"
        + "  Для периодов с 'd' суффиксом включается частичный текущий день (N+1 бакетов)."
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
            # Validate generate-command (must be non-empty list[str] of non-empty strings)
            generateCommand = statsPagesConfig.get("generate-command")
            if (
                not generateCommand
                or not isinstance(generateCommand, list)
                or len(generateCommand) == 0
                or not all(isinstance(item, str) and item.strip() for item in generateCommand)
            ):
                raise RuntimeError(
                    "[stats.pages] generate-command must be a non-empty list[str] of non-empty strings when enabled"
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
                    "[stats.pages] delete-command must be a non-empty list[str] of non-empty strings when enabled"
                )

            # Validate ttl-hours is positive int
            ttlHours = statsPagesConfig.get("ttl-hours", 24)
            if not isinstance(ttlHours, int) or ttlHours <= 0:
                raise RuntimeError("[stats.pages] ttl-hours must be a positive integer when enabled")

            # Cache validated config values (already lists from above validation)
            self._statsPagesTtlHours = ttlHours
            self._statsPagesGenerateCommand = generateCommand
            self._statsPagesDeleteCommand = deleteCommand
            self._statsPagesRatelimiterQueue = statsPagesConfig.get("ratelimiter-queue", "stats-pages")

        # D14: Register cleanup handler (unconditionally when StatsHandler is constructed)
        QueueService.getInstance().registerDelayedTaskHandler(
            DelayedTaskFunction.STATS_PAGES_CLEANUP, self._dtStatsPagesCleanup
        )

    def _formatCount(self, value: int) -> str:
        """Format a count value with k/m/g suffixes for readability.

        Values below 1000 are rendered as-is. Values >= 1000 are scaled to k/m/g
        with 3 significant digits, using comma as the decimal separator.

        Args:
            value: The count value to format.

        Returns:
            Formatted string representation.
        """
        if value < 1000:
            return str(value)

        # Round to 3 significant digits first
        # Example: 999999 → 1_000_000 (3 sig figs), 1234567 → 1_230_000 (3 sig figs)
        roundedValue = self._roundToSignificantDigits(value, 3)

        # Determine divisor tier based on rounded value
        if roundedValue < 1_000_000:
            divisor = 1_000
            suffix = "k"
        elif roundedValue < 1_000_000_000:
            divisor = 1_000_000
            suffix = "m"
        else:
            divisor = 1_000_000_000
            suffix = "g"

        scaled = roundedValue / divisor

        # Determine decimal places for 3 significant digits
        if scaled < 10:
            decimals = 2
        elif scaled < 100:
            decimals = 1
        else:
            decimals = 0

        # Format with specified decimals
        formatted = f"{scaled:.{decimals}f}"

        # Strip trailing zeros and dangling separator, but only if there was a decimal point
        # This prevents stripping trailing zeros from integer representations like "390"
        if decimals > 0:
            formatted = formatted.rstrip("0").rstrip(".")

        # Replace dot with comma for Russian locale
        formatted = formatted.replace(".", ",")

        return formatted + suffix

    def _roundToSignificantDigits(self, value: int, sigFigs: int) -> int:
        """Round a value to the specified number of significant digits.

        Args:
            value: The value to round.
            sigFigs: Number of significant digits.

        Returns:
            Rounded integer value.
        """
        if value == 0:
            return 0

        order = int(math.log10(abs(value)))
        divisor = 10 ** (order - sigFigs + 1)
        return int(round(value / divisor) * divisor)

    def _formatDuration(self, seconds: float, subMinuteDecimals: int = 2) -> str:
        """Format a duration in seconds to human-readable compound format.

        Sub-minute values keep their decimal precision via subMinuteDecimals param.
        Values >= 60s use compound format (Xm Ys), values >= 3600s use (Xh Ym Zs).

        Args:
            seconds: Duration in seconds.
            subMinuteDecimals: Number of decimals for sub-minute values (default 2).

        Returns:
            Formatted duration string.
        """
        if seconds < 60:
            return f"{seconds:.{subMinuteDecimals}f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.1f}s"
        else:
            hours = int(seconds // 3600)
            remainingSeconds = seconds % 3600
            minutes = int(remainingSeconds // 60)
            secs = remainingSeconds % 60
            return f"{hours}h {minutes:02d}m {secs:.1f}s"

    @commandHandlerV2(
        commands=("stats", "stats_web"),
        shortDescription="[help|chatId] [--period=...] [--section=...] [--user=<id>] [--web] - Statistics",
        helpMessage=_HELP_TEXT,
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.UTILITIES,
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

        Returns:
            None
        """
        # Apply ALLOW_SHOW_STATS gate for group/channel chats only
        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
            if not chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS].toBool():
                # Respect DELETE_DENIED_COMMANDS setting
                if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                    try:
                        await self.deleteMessage(ensuredMessage)
                    except Exception as e:
                        logger.error(f"Failed to delete denied stats command: {e}")
                    return
                else:
                    # Informative reply when DELETE_DENIED_COMMANDS is false
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

        # Resolve --user argument (can be numeric ID or @username)
        # Resolution happens AFTER targetChatId is known
        filterUserId = None
        if parsedArgs["user"] is not None:
            userValue = parsedArgs["user"]
            if userValue.startswith("@"):
                # Username resolution - strip leading @
                username = userValue[1:]
                chatUser = await self.db.chatUsers.getChatUserByUsername(chatId=targetChatId, username=username)
                if chatUser is None:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"❌ Пользователь @{username} не найден в этом чате.",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                        typingManager=typingManager,
                    )
                    return
                filterUserId = chatUser["user_id"]
            else:
                # Numeric ID
                try:
                    filterUserId = int(userValue)
                except (ValueError, TypeError):
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"❌ Неверный user ID: {userValue}. Используйте числовой ID или @username.",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                        typingManager=typingManager,
                    )
                    return

        # Map period arg to period type and compute range (I1: wrap to catch ValueError)
        periodArg = parsedArgs["period"]
        try:
            periodType = mapPeriodArgToPeriodType(periodArg)
            periodStartFrom, periodStartTo = computePeriodRange(periodArg)
        except ValueError:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"❌ Неверный период: {periodArg}\n\n{self._USAGE_TEXT}",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Handle web mode (D10/D11/D13/D14/D15)
        if parsedArgs["web"]:
            if not self._statsPagesEnabled:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=("⚠ Генерация веб-страниц отключена."),
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
                    filterUserId=filterUserId,
                    positionalChatIdUsed=positionalChatIdUsed,
                    typingManager=typingManager,
                )
            except Exception as e:
                logger.exception(f"Web mode failed for chat {targetChatId}: {e}")
                # D15: Note sent alone if exception occurred before brief was built (e.g., rate-limit check failed)
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
                filterUserId=filterUserId,
                positionalChatIdUsed=positionalChatIdUsed,
            )
            await self._sendStatsReply(
                ensuredMessage=ensuredMessage,
                replyText=messageText,
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
                "period": "7d",
                "section": "messages",
                "user": None,
                "web": forceWeb,
            }

        # Split into tokens
        tokens = args.split()

        # Normalize em-dash/en-dash to double dash for autocorrect compatibility
        # Phone/laptop autocorrect often replaces -- with — (U+2014) or – (U+2013)
        # We normalize ONLY leading runs of these characters to avoid breaking negative chatIds
        normalizedTokens: list[str] = []
        for token in tokens:
            # Find leading run of em-dash or en-dash characters
            leadingDashRun = ""
            remainingPart = token
            for char in token:
                if char in ("—", "–"):  # U+2014 em-dash, U+2013 en-dash
                    leadingDashRun += char
                else:
                    remainingPart = token[len(leadingDashRun) :]
                    break
            else:
                # Loop completed without hitting non-dash (entire token is dashes)
                remainingPart = ""
            # Replace leading dash run with -- if present, otherwise keep original token
            if leadingDashRun:
                normalizedTokens.append("--" + remainingPart)
            else:
                normalizedTokens.append(token)
        tokens = normalizedTokens

        # Positional arguments (at most one: help OR chatId)
        positional: list[str] = []
        options: dict[str, str] = {}

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
                        # --period, --section, --user require a value
                        if optionName in ("period", "section", "user"):
                            raise StatsUsageError(f"Опция --{optionName} требует значения")
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
                # Token already validated as int in _parseStatsArgs parsing loop, so this conversion cannot fail
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
        period: str = options.get("period", "7d")
        section: str = options.get("section", "messages")
        if section not in ("messages", "commands", "tools", "llm", "all"):
            raise StatsUsageError(f"Неизвестный раздел: {section}. Используйте messages, commands, tools, llm, или all")

        # User can be numeric ID or @username (stored as string, resolved later)
        user: Optional[str] = options.get("user")

        web: bool = "web" in options or forceWeb

        return ParsedStatsArgs(
            help=positional == ["help"],
            chatId=chatId,
            period=period,
            section=section,
            user=user,
            web=web,
        )

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
    ) -> str | list[str]:
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
            positionalChatIdUsed: Whether a positional chatId was provided (gates chat list).

        Returns:
            Formatted markdown reply string (or list of strings for chunked output).
        """
        # Scope: group → this chat only, private → this chat or member chat
        consumerFilter = {str(targetChatId)}

        # D7 drill-down depth: --section=all renders all four sections
        sectionsToRender: list[str]
        if section == "all":
            # --section=all: render all four sections
            sectionsToRender = ["messages", "commands", "tools", "llm"]
        else:
            # Default: single section (the one specified)
            sectionsToRender = [section]

        # Build reply
        lines: list[str] = []

        # Header
        periodLabel = periodArg if periodArg != "all" else "всё время"

        # Get chat title for pretty header, fallback to #id if unavailable
        chatIdentifier = f"#{targetChatId}"
        try:
            chatInfo = await self.cache.getChatInfo(chatId=targetChatId)
            if chatInfo:
                chatIdentifier = self.getChatTitle(chatInfo, useMarkdown=True, addChatId=True, addChatType=False)
        except Exception:
            # Fallback to simple #id format if chat info is unavailable
            logger.debug(f"Failed to get chat info for chat {targetChatId}, using #id fallback")
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
        if (
            chatType == ChatType.PRIVATE
            and section == "messages"
            and filterUserId is None
            and positionalChatIdUsed is False
        ):
            lines.append("")
            lines.append("Ваши чаты:")
            userChats = await self.getUserChats(userId)
            # Sort by messages_count descending, top 10
            userChats.sort(key=lambda c: c.get("messages_count", 0), reverse=True)
            for chat in userChats[:10]:
                chatId = chat["chat_id"]
                title = chat["title"] or chat["username"] or ""
                msgCount = chat.get("messages_count", 0)
                lines.append(f"  #`{chatId}` {title} — {self._formatCount(msgCount)}")
            if len(userChats) > 10:
                lines.append(f"  … и ещё {self._formatCount(len(userChats) - 10)} чатов")

        # Footer
        lines.append("")
        lines.append("/stats help — полная справка")

        # Send output in chunks to avoid hitting message size limits
        # Pre-group lines into atomic units (lone lines or fenced blocks) to ensure fence atomicity
        chunks = self._chunkLinesWithFenceAtomicity(lines)

        return chunks[0] if len(chunks) == 1 else chunks

    def _chunkLinesWithFenceAtomicity(self, lines: list[str]) -> list[str]:
        """Chunk lines into output messages while preserving fence atomicity.

        A fenced code block must never be split across chunks. This method
        pre-groups lines into atomic units (lone lines or complete fenced blocks),
        then chunks by units with the existing length accounting.

        Note on current usage: callers typically pass whole multi-line section
        strings as single `lines` elements (e.g., entire LLM or STT sub-blocks
        as one unit). In this mode, the fence-detection branch (below) is dead
        code because "```" never matches a flat line element. Atomicity is
        guaranteed by the unit granularity (whole sections are never split).
        However, if flat lines are ever passed in the future, the fence-tracking
        branch will enforce atomicity for fenced blocks that span multiple lines.
        The fence-tracking branch handles caption-in-fence openers (e.g., ```` ```Top: ````)
        by detecting any line whose stripped form starts with "```".

        Args:
            lines: List of lines to chunk. May contain flat lines or multi-line
                   section strings as elements.

        Returns:
            List of chunk strings.
        """
        # Pre-group lines into atomic units
        units: list[list[str]] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip().startswith("```"):
                # Start of a fenced block - collect the entire block as one unit
                # (handles caption-in-fence openers like "```Top:" or "```Top\xa0models:")
                unit = [line]
                i += 1
                # Collect lines until closing ```
                while i < len(lines) and lines[i].strip() != "```":
                    unit.append(lines[i])
                    i += 1
                if i < len(lines):
                    # Add closing ``` to the unit
                    unit.append(lines[i])
                    i += 1
                units.append(unit)
            else:
                # Lone line is its own unit
                units.append([line])
                i += 1

        # Now chunk by units with length accounting
        chunks: list[str] = []
        currentChunk: list[str] = []
        currentLength = 0

        for unit in units:
            unitLength = sum(len(line) + 1 for line in unit)  # +1 for newline per line

            if currentLength + unitLength > self._OUTPUT_CHUNK_LENGTH and currentChunk:
                # Flush current chunk before adding this unit
                chunks.append("\n".join(currentChunk))
                currentChunk = unit[:]
                currentLength = unitLength
            else:
                currentChunk.extend(unit)
                currentLength += unitLength

        # Don't forget the last chunk (ensure at least one message is sent)
        if currentChunk:
            chunks.append("\n".join(currentChunk))

        return chunks

    def _renderFencedTopBlock(self, items: list[tuple[str, int]], blockTitle: str = "Top:") -> list[str]:
        """Render a fenced code block with aligned columns for top items.

        The caption (blockTitle) is rendered as the language/info-string on the
        opening fence line, which Telegram renders as the block's caption.
        Spaces in multi-word captions are replaced with non-breaking spaces (U+00A0).

        Args:
            items: List of (key, count) tuples to render.
            blockTitle: Title to render as the fence caption (e.g., "Top:", "Top models:").

        Returns:
            List of strings representing the fenced block (caption-in-fence opening,
            bullet lines, closing fence). Example: ["```Top:", "• key  123", "```"]
        """
        if not items:
            return []

        blockLines: list[str] = []
        maxKeyWidth = 0
        maxCountWidth = 0
        itemsWithFormattedCounts: list[tuple[str, str]] = []
        for key, count in items:
            formattedCount = self._formatCount(int(count))
            itemsWithFormattedCounts.append((key, formattedCount))
            maxKeyWidth = max(maxKeyWidth, len(key))
            maxCountWidth = max(maxCountWidth, len(formattedCount))

        for key, formattedCount in itemsWithFormattedCounts:
            blockLines.append(f"• {key.ljust(maxKeyWidth)}  {formattedCount.rjust(maxCountWidth)}")

        if blockLines:
            return ["```" + blockTitle.replace(" ", " "), *blockLines, "```"]
        return []

    async def _sendStatsReply(
        self,
        ensuredMessage: EnsuredMessage,
        replyText: str | list[str],
        typingManager: Optional[TypingManager],
    ) -> None:
        """Send the stats reply, handling chunked output if needed.

        Args:
            ensuredMessage: The originating user message.
            replyText: The reply text (string for single message, or list of strings for chunks).
            typingManager: Optional typing indicator manager.

        Returns:
            None
        """
        if isinstance(replyText, str):
            # Single message (most common case)
            await self.sendMessage(
                ensuredMessage,
                messageText=replyText,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
        else:
            # Multiple chunks - send sequentially with pacing
            for i, chunk in enumerate(replyText):
                await self.sendMessage(
                    ensuredMessage,
                    messageText=chunk,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                # Sleep after each chunk except the last
                if i < len(replyText) - 1:
                    await asyncio.sleep(self._CHUNK_SEND_DELAY_SECONDS)

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
            limit=STATS_QUERY_ROW_LIMIT,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == STATS_QUERY_ROW_LIMIT

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        # Apply user filter if specified
        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        # Build lines using the shared helper
        lines = await self._buildMessagesBreakdownLines(analyzer, targetChatId)

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполны")

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
            limit=STATS_QUERY_ROW_LIMIT,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == STATS_QUERY_ROW_LIMIT

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        totalCommands = analyzer.sumMetric("command_count")
        errorCommands = analyzer.sumMetric("is_error")

        topCommands = analyzer.topN("commandName", "command_count", 3)

        lines: list[str] = [f"**Commands:** {self._formatCount(int(totalCommands))}"]
        if errorCommands > 0:
            lines.append(f"  ⚠ errors: {self._formatCount(int(errorCommands))}")
        if topCommands:
            cmdNamesWithCounts: list[tuple[str, int]] = [(cmdName, int(count)) for cmdName, count in topCommands]
            lines.extend(self._renderFencedTopBlock(cmdNamesWithCounts))

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполны")

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
            limit=STATS_QUERY_ROW_LIMIT,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == STATS_QUERY_ROW_LIMIT

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        if filterUserId is not None:
            analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

        totalCalls = analyzer.sumMetric("tool_call_count")
        errorCalls = analyzer.sumMetric("is_error")

        # Cross-group contract: use tool_exec_count when available, fallback to tool_call_count
        toolExecCountSum = analyzer.sumMetric("tool_exec_count")
        avgElapsed = 0.0
        if toolExecCountSum > 0:
            elapsedTimeSum = analyzer.sumMetric("elapsed_time")
            avgElapsed = elapsedTimeSum / toolExecCountSum
        else:
            avgElapsed = analyzer.average("elapsed_time", "tool_call_count")

        topTools = analyzer.topN("toolName", "tool_call_count", 3)

        # Build header with optional avg time folded in
        header = f"**Tools:** {self._formatCount(int(totalCalls))}"
        if avgElapsed > 0:
            header += f" · avg {self._formatDuration(avgElapsed)}"
        lines: list[str] = [header]
        if errorCalls > 0:
            lines.append(f"  ⚠ errors: {self._formatCount(int(errorCalls))}")
        if topTools:
            toolNamesWithCounts: list[tuple[str, int]] = [(toolName, int(count)) for toolName, count in topTools]
            lines.extend(self._renderFencedTopBlock(toolNamesWithCounts))

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполны")

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
            limit=STATS_QUERY_ROW_LIMIT,
        )

        # D5 honesty line: check if we hit the limit
        possiblyIncomplete = len(rows) == STATS_QUERY_ROW_LIMIT

        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        totalRequests = analyzer.sumMetric("request_count")
        errorRequests = analyzer.sumMetric("is_error")
        totalInputTokens = analyzer.sumMetric("input_tokens")
        totalOutputTokens = analyzer.sumMetric("output_tokens")

        avgElapsed = analyzer.average("elapsed_time", "request_count")

        topModels = analyzer.topN("modelName", "request_count", 3)

        # Build header with avg time folded in
        header = f"**LLM:** {self._formatCount(int(totalRequests))} requests"
        if avgElapsed > 0:
            header += f" · avg {self._formatDuration(avgElapsed)}"
        lines: list[str] = [header]
        if errorRequests > 0:
            lines.append(f"  ⚠ errors: {self._formatCount(int(errorRequests))}")
        tokensLine = (
            f"tokens: in {self._formatCount(int(totalInputTokens))} / out {self._formatCount(int(totalOutputTokens))}"
        )
        lines.append(tokensLine)
        if topModels:
            modelNamesWithCounts: list[tuple[str, int]] = [(modelName, int(count)) for modelName, count in topModels]
            lines.extend(self._renderFencedTopBlock(modelNamesWithCounts, "Top models:"))

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
            limit=STATS_QUERY_ROW_LIMIT,
        )

        # D5 honesty line: check if we hit the STT limit
        sttPossiblyIncomplete = len(sttRows) == STATS_QUERY_ROW_LIMIT

        if sttRows:
            sttAnalyzer = StatsAnalyzer(sttRows)
            sttAnalyzer = sttAnalyzer.filterByLabelIn("consumer", consumerFilter)

            totalSttRequests = sttAnalyzer.sumMetric("request_count")
            errorSttRequests = sttAnalyzer.sumMetric("is_error")
            totalAudioDurationMs = sttAnalyzer.sumMetric("audio_duration_ms")
            totalSttElapsedTime = sttAnalyzer.sumMetric("elapsed_time")

            lines.append(f"  **STT:** {self._formatCount(int(totalSttRequests))}")
            if errorSttRequests > 0:
                lines.append(f"    errors: {self._formatCount(int(errorSttRequests))}")
            if totalAudioDurationMs > 0:
                audioDurationSecs = totalAudioDurationMs / 1000.0
                lines.append(f"    audio: {self._formatDuration(audioDurationSecs, subMinuteDecimals=1)}")
            if totalSttRequests > 0:
                avgSttTime = totalSttElapsedTime / totalSttRequests
                lines.append(f"    avg time: {self._formatDuration(avgSttTime)}")

            # D5 honesty line for STT
            if sttPossiblyIncomplete:
                lines.append("    ⚠ результаты возможно неполны")

        # D5 honesty line
        if possiblyIncomplete:
            lines.append("  ⚠ результаты возможно неполны")

        return "\n".join(lines)

    async def _resolveUserName(self, chatId: int, userId: int) -> str:
        """Resolve a user ID to a display name for stats.

        Args:
            chatId: Chat ID to look up user in.
            userId: User ID to resolve.

        Returns:
            Display name (plain @username, or full_name, or raw ID as fallback).
            Note: Backticks are NOT added here; callers wrap when needed.
        """
        try:
            chatUser = await self.cache.getChatUser(chatId=chatId, userId=userId)
            if chatUser:
                username = chatUser.get("username")
                fullName = chatUser.get("full_name")
                if username:
                    # Normalize to exactly one @
                    if username.startswith("@"):
                        return username
                    else:
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
        section: str,
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
            section: Section to display (for chat list condition).
            periodType: Period granularity for queries.
            periodStartFrom: ISO-8601 UTC start bound (None for 'all').
            periodStartTo: ISO-8601 UTC end bound (None for 'all').
            filterUserId: Optional user ID filter for drill-down.
            positionalChatIdUsed: Whether a positional chatId was provided.

        Returns:
            StatsPayload dict with all required meta fields and raw rows.
        """

        # Query all five event types
        eventTypes = ["message", "command", "llm_tool_call", "llm_request", "stt_request"]
        rows: dict[str, list[StatsAggregateDict]] = {eventType: [] for eventType in eventTypes}
        truncatedEventTypes: list[str] = []

        # Consumer filter for target chat (excludes __global__ and other chats)
        consumerFilter = {str(targetChatId)}

        for eventType in eventTypes:
            storage = self.statsAggregationService.getQueryStorage(eventType)
            queriedRows = await storage.query(
                eventType=eventType,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                limit=STATS_QUERY_ROW_LIMIT,
            )

            # Track truncation BEFORE filtering (honesty line needs this)
            if len(queriedRows) == STATS_QUERY_ROW_LIMIT:
                truncatedEventTypes.append(eventType)

            # Filter by consumer label to exclude __global__ and other chats
            analyzer = StatsAnalyzer(queriedRows)
            analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

            # Apply user filter for user-level event types only
            if filterUserId is not None and eventType in ("message", "command", "llm_tool_call"):
                analyzer = analyzer.filterByLabel("user_id", str(filterUserId))

            rows[eventType] = analyzer.rows

        # Chat list for private scope (match reply path condition exactly)
        # Condition: private ∧ no user filter ∧ no positional chatId ∧ messages section
        chatList: list[ChatListEntry] = []
        chatListTotal: int = 0
        if (
            chatType == ChatType.PRIVATE
            and filterUserId is None
            and positionalChatIdUsed is False
            and section == "messages"
        ):
            userChats = await self.getUserChats(userId)
            # Store total count before slicing (for trailer display)
            chatListTotal = len(userChats)
            # Sort by messages_count descending, top 10
            userChats.sort(key=lambda c: c.get("messages_count", 0), reverse=True)
            for chat in userChats[:10]:
                chatList.append(
                    {
                        "chatId": chat["chat_id"],
                        "title": chat["title"] or chat["username"] or "",
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

        # Build payload with raw rows
        payload: StatsPayload = {
            "userId": str(userId),
            "chatId": str(targetChatId),
            "chatTitle": chatTitle,
            "chatType": chatType.value,
            "platform": self.botProvider.value,
            "period": periodArg,
            "periodType": periodType,
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "rows": rows,
        }

        if chatList:
            payload["chatList"] = chatList
            payload["chatListTotal"] = chatListTotal

        if truncatedEventTypes:
            payload["truncatedEventTypes"] = truncatedEventTypes

        if filterUserId is not None:
            payload["userFilterApplied"] = True

        return payload

    async def _appendWebSuffix(self, messageText: str | list[str], suffix: str) -> str | list[str]:
        """Append a suffix to messageText, handling both str and list[str] shapes.

        If messageText is a string, appends the suffix with a blank line separator.
        If messageText is a list of strings, appends the suffix to the last chunk.

        Args:
            messageText: The message text (string or list of strings).
            suffix: The suffix to append (e.g., failure note or page link).

        Returns:
            The message text with suffix appended (str or list[str]).
        """
        if isinstance(messageText, str):
            return f"{messageText}\n\n{suffix}"
        else:
            # Append to the last chunk
            lastChunk = messageText[-1]
            messageText[-1] = f"{lastChunk}\n\n{suffix}"
            return messageText

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
        # D13: Rate limit check FIRST - U12-6: applyLimit-only
        # Key limiter on ISSUING chat (ensuredMessage.recipient.id), not target chat
        rateLimiterKey = f"stats-pages-{ensuredMessage.recipient.id}"

        # U12-6: applyLimit-only - NO pre-check, NO refusal reply
        # Just apply the limit (this may sleep until a slot is available)
        # No try/except here; outer D15 wrap covers the no-limiter RuntimeError
        await RateLimiterManager.getInstance().applyLimit(self._statsPagesRatelimiterQueue, rateLimiterKey)

        # Build payload for subprocess (single-pass: derive brief from payload)
        try:
            payload = await self._buildStatsPayload(
                targetChatId=targetChatId,
                chatType=chatType,
                userId=userId,
                periodArg=periodArg,
                section=section,
                periodType=periodType,
                periodStartFrom=periodStartFrom,
                periodStartTo=periodStartTo,
                filterUserId=filterUserId,
                positionalChatIdUsed=positionalChatIdUsed,
            )
        except Exception:
            logger.exception(f"Stats payload build failed for chat {targetChatId}")
            # No brief yet, send generic error
            await self.sendMessage(
                ensuredMessage,
                messageText="❌ Ошибка при запросе статистики.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Derive brief from payload (single-pass: no dual query)
        try:
            brief = await self._buildStatsReplyFromPayload(
                payload=payload,
                targetChatId=targetChatId,
                chatType=chatType,
                userId=userId,
                section=section,
                periodArg=periodArg,
                filterUserId=filterUserId,
                positionalChatIdUsed=positionalChatIdUsed,
            )
        except Exception:
            logger.exception(f"Stats brief build from payload failed for chat {targetChatId}")
            # Brief build failed - still have payload for subprocess, but send generic error
            brief = "❌ Ошибка при формировании сводки."

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
            await self._sendStatsReply(
                ensuredMessage,
                await self._appendWebSuffix(brief, "⚠ Генерация веб-страницы не удалась (ошибка конфигурации)."),
                typingManager,
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
                await self._sendStatsReply(
                    ensuredMessage,
                    await self._appendWebSuffix(brief, "⚠ Генерация веб-страницы не удалась (тайм-аут)."),
                    typingManager,
                )
                return
            else:
                # SPAWN or other error
                logger.warning("stats-pages generate failed for chat %s: %s", targetChatId, e.message)
                # Fall back to in-chat reply with failure note
                await self._sendStatsReply(
                    ensuredMessage,
                    await self._appendWebSuffix(brief, "⚠ Генерация веб-страницы не удалась."),
                    typingManager,
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
            await self._sendStatsReply(
                ensuredMessage,
                await self._appendWebSuffix(brief, "⚠ Генерация веб-страницы не удалась."),
                typingManager,
            )
            return

        # Parse stdout JSON
        try:
            result = json.loads(stdout)
            pageId = result["pageId"]  # U12-5: key renamed from "id" to "pageId"
            url = result["url"]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("stats-pages generate returned invalid JSON for chat %s: %s", targetChatId, e)
            # Fall back to in-chat reply with failure note
            await self._sendStatsReply(
                ensuredMessage,
                await self._appendWebSuffix(brief, "⚠ Генерация веб-страницы не удалась (неверный ответ)."),
                typingManager,
            )
            return

        # Use the URL as-is (CLI returns verbatim URL)
        fullLink = url

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
        await self._sendStatsReply(
            ensuredMessage,
            await self._appendWebSuffix(brief, f"📊 Страница: {fullLink}"),
            typingManager,
        )

    async def _buildStatsReplyFromPayload(
        self,
        payload: StatsPayload,
        targetChatId: int,
        chatType: ChatType,
        userId: int,
        section: str,
        periodArg: str,
        filterUserId: Optional[int],
        positionalChatIdUsed: bool = False,
    ) -> str | list[str]:
        """Build the stats reply message from an already-built payload.

        Derives the brief from the payload data without additional queries.
        Reuses the handler's rendering logic on the payload's rows/sections.

        Args:
            payload: The stats payload with rows and metadata.
            targetChatId: Chat to show stats for (for header label).
            chatType: Type of the target chat (for chat list condition).
            userId: Current user ID (for chat list if private).
            section: Section to display (for chat list condition).
            periodArg: Original period argument string (for header label).
            filterUserId: Optional user ID filter (for display).
            positionalChatIdUsed: Whether a positional chatId was provided (gates chat list).

        Returns:
            Formatted markdown reply string (or list of strings for chunked output).
        """
        # Scope: group → this chat only, private → this chat or member chat
        consumerFilter = {str(targetChatId)}

        # D7 drill-down depth: --section=all renders all four sections
        sectionsToRender: list[str]
        if section == "all":
            # --section=all: render all four sections
            sectionsToRender = ["messages", "commands", "tools", "llm"]
        else:
            # Default: single section (the one specified)
            sectionsToRender = [section]

        # Build reply
        lines: list[str] = []

        # Header
        periodLabel = periodArg if periodArg != "all" else "всё время"
        # Get chat title for pretty header, fallback to #id if unavailable
        chatIdentifier = f"#{targetChatId}"
        try:
            chatInfo = await self.cache.getChatInfo(chatId=targetChatId)
            if chatInfo:
                chatIdentifier = self.getChatTitle(chatInfo, useMarkdown=True, addChatId=True, addChatType=False)
        except Exception:
            # Fallback to simple #id format if chat info is unavailable
            logger.debug(f"Failed to get chat info for chat {targetChatId}, using #id fallback")
        lines.append(f"📊 Stats — {periodLabel} (UTC) — {chatIdentifier}")

        # Build section views from payload rows
        for renderSection in sectionsToRender:
            sectionView = await self._buildSectionViewFromPayload(
                payload=payload,
                section=renderSection,
                consumerFilter=consumerFilter,
                targetChatId=targetChatId,
            )
            lines.append(sectionView)
            if renderSection != sectionsToRender[-1]:
                lines.append("")  # Blank line between sections

        # In private scope, add chat list from payload if available
        if (
            chatType == ChatType.PRIVATE
            and section == "messages"
            and filterUserId is None
            and positionalChatIdUsed is False
            and "chatList" in payload
        ):
            lines.append("")
            lines.append("Ваши чаты:")
            for chat in payload["chatList"]:
                chatId = chat["chatId"]
                title = chat["title"]
                msgCount = chat["messagesCount"]
                lines.append(f"  #`{chatId}` {title} — {self._formatCount(msgCount)}")
            if "chatListTotal" in payload and payload["chatListTotal"] > len(payload["chatList"]):
                lines.append(
                    f"  … и ещё {self._formatCount(payload['chatListTotal'] - len(payload['chatList']))} чатов"
                )

        # Footer
        lines.append("")
        lines.append("/stats help — полная справка")

        # Add honesty line for truncated data
        if "truncatedEventTypes" in payload and payload["truncatedEventTypes"]:
            lines.append("")
            lines.append("  ⚠ результаты возможно неполны")

        # Send output in chunks to avoid hitting message size limits
        # Pre-group lines into atomic units (lone lines or fenced blocks) to ensure fence atomicity
        chunks = self._chunkLinesWithFenceAtomicity(lines)

        return chunks[0] if len(chunks) == 1 else chunks

    async def _buildSectionViewFromPayload(
        self,
        payload: StatsPayload,
        section: str,
        consumerFilter: set[str],
        targetChatId: int,
    ) -> str:
        """Build the view for a specific stats section from payload data.

        Args:
            payload: The stats payload with all rows.
            section: Section to display.
            consumerFilter: Consumer IDs to filter by.
            targetChatId: Chat to show stats for (for username resolution).

        Returns:
            Formatted section view string.
        """
        rows = payload["rows"][section] if section in payload["rows"] else []
        analyzer = StatsAnalyzer(rows)
        analyzer = analyzer.filterByLabelIn("consumer", consumerFilter)

        # Section builders (reusing the same logic as _buildSectionView)
        if section == "messages":
            return await self._buildMessagesSectionFromAnalyzer(
                analyzer, payload["truncatedEventTypes"] if "truncatedEventTypes" in payload else [], targetChatId
            )
        elif section == "commands":
            return self._buildCommandsSectionFromAnalyzer(
                analyzer, payload["truncatedEventTypes"] if "truncatedEventTypes" in payload else []
            )
        elif section == "tools":
            return self._buildToolsSectionFromAnalyzer(
                analyzer, payload["truncatedEventTypes"] if "truncatedEventTypes" in payload else []
            )
        elif section == "llm":
            return self._buildLlmSectionFromAnalyzer(
                analyzer, payload, payload["truncatedEventTypes"] if "truncatedEventTypes" in payload else []
            )
        else:
            return f"❌ Неизвестный раздел: {section}"

    async def _buildMessagesBreakdownLines(self, analyzer: StatsAnalyzer, targetChatId: int) -> list[str]:
        """Build messages breakdown and top users lines.

        Args:
            analyzer: StatsAnalyzer with filtered data.
            targetChatId: Chat to show stats for (for username resolution).

        Returns:
            List of formatted message breakdown lines.
        """
        totalMessageCount = analyzer.sumMetric("message_count")

        # Top users (by message count) - rows with sent=False or absent
        userRows = [row for row in analyzer.rows if row["labels"].get("sent", "False") == "False"]
        userAnalyzer = StatsAnalyzer(userRows)
        topUsers = userAnalyzer.topN("user_id", "message_count", 3)

        # Build lines
        lines: list[str] = [f"**Messages:** {self._formatCount(int(totalMessageCount))}"]

        if topUsers:
            # Process user names before rendering (unique to messages section)
            userNamesWithCounts: list[tuple[str, int]] = []
            for userIdStr, count in topUsers:
                try:
                    userIdInt = int(userIdStr)
                except (ValueError, TypeError):
                    userIdInt = 0  # Fallback for invalid user IDs
                userName = await self._resolveUserName(targetChatId, userIdInt)
                # Strip backticks from usernames (returned by _resolveUserName)
                # since they'll be inside a code block. Also protects fenced-block
                # content when the full_name fallback contains a backtick.
                userName = userName.replace("`", "")
                userNamesWithCounts.append((userName, int(count)))
            lines.extend(self._renderFencedTopBlock(userNamesWithCounts))

        return lines

    async def _buildMessagesSectionFromAnalyzer(
        self, analyzer: StatsAnalyzer, truncatedEventTypes: list[str], targetChatId: int
    ) -> str:
        """Build the messages section view from analyzer.

        Args:
            analyzer: StatsAnalyzer with filtered data.
            truncatedEventTypes: List of event types that were truncated (unused, honesty line is global).
            targetChatId: Chat to show stats for (for username resolution).

        Returns:
            Formatted messages section string.
        """
        lines = await self._buildMessagesBreakdownLines(analyzer, targetChatId)
        return "\n".join(lines)

    def _buildCommandsSectionFromAnalyzer(self, analyzer: StatsAnalyzer, truncatedEventTypes: list[str]) -> str:
        """Build the commands section view from analyzer.

        Args:
            analyzer: StatsAnalyzer with filtered data.
            truncatedEventTypes: List of event types that were truncated (unused, honesty line is global).

        Returns:
            Formatted commands section string.
        """
        totalCommands = analyzer.sumMetric("command_count")
        errorCommands = analyzer.sumMetric("is_error")

        topCommands = analyzer.topN("commandName", "command_count", 3)

        lines: list[str] = [f"**Commands:** {self._formatCount(int(totalCommands))}"]
        if errorCommands > 0:
            lines.append(f"  ⚠ errors: {self._formatCount(int(errorCommands))}")
        if topCommands:
            cmdNamesWithCounts: list[tuple[str, int]] = [(cmdName, int(count)) for cmdName, count in topCommands]
            lines.extend(self._renderFencedTopBlock(cmdNamesWithCounts))

        return "\n".join(lines)

    def _buildToolsSectionFromAnalyzer(self, analyzer: StatsAnalyzer, truncatedEventTypes: list[str]) -> str:
        """Build the tools section view from analyzer.

        Args:
            analyzer: StatsAnalyzer with filtered data.
            truncatedEventTypes: List of event types that were truncated (unused, honesty line is global).

        Returns:
            Formatted tools section string.
        """
        totalCalls = analyzer.sumMetric("tool_call_count")
        errorCalls = analyzer.sumMetric("is_error")

        # Cross-group contract: use tool_exec_count when available, fallback to tool_call_count
        toolExecCountSum = analyzer.sumMetric("tool_exec_count")
        avgElapsed = 0.0
        if toolExecCountSum > 0:
            elapsedTimeSum = analyzer.sumMetric("elapsed_time")
            avgElapsed = elapsedTimeSum / toolExecCountSum
        else:
            avgElapsed = analyzer.average("elapsed_time", "tool_call_count")

        topTools = analyzer.topN("toolName", "tool_call_count", 3)

        # Build header with optional avg time folded in
        header = f"**Tools:** {self._formatCount(int(totalCalls))}"
        if avgElapsed > 0:
            header += f" · avg {self._formatDuration(avgElapsed)}"
        lines: list[str] = [header]
        if errorCalls > 0:
            lines.append(f"  ⚠ errors: {self._formatCount(int(errorCalls))}")
        if topTools:
            toolNamesWithCounts: list[tuple[str, int]] = [(toolName, int(count)) for toolName, count in topTools]
            lines.extend(self._renderFencedTopBlock(toolNamesWithCounts))

        return "\n".join(lines)

    def _buildLlmSectionFromAnalyzer(
        self, analyzer: StatsAnalyzer, payload: StatsPayload, truncatedEventTypes: list[str]
    ) -> str:
        """Build the LLM section view from analyzer.

        Args:
            analyzer: StatsAnalyzer with filtered data.
            payload: The stats payload (for STT data and user filter annotation).
            truncatedEventTypes: List of event types that were truncated (unused for LLM, honesty line is global).

        Returns:
            Formatted LLM section string.
        """
        totalRequests = analyzer.sumMetric("request_count")
        errorRequests = analyzer.sumMetric("is_error")
        totalInputTokens = analyzer.sumMetric("input_tokens")
        totalOutputTokens = analyzer.sumMetric("output_tokens")

        avgElapsed = analyzer.average("elapsed_time", "request_count")

        topModels = analyzer.topN("modelName", "request_count", 3)

        # Build header with avg time folded in
        header = f"**LLM:** {self._formatCount(int(totalRequests))} requests"
        if avgElapsed > 0:
            header += f" · avg {self._formatDuration(avgElapsed)}"
        lines: list[str] = [header]
        if errorRequests > 0:
            lines.append(f"  ⚠ errors: {self._formatCount(int(errorRequests))}")
        tokensLine = (
            f"tokens: in {self._formatCount(int(totalInputTokens))} / out {self._formatCount(int(totalOutputTokens))}"
        )
        lines.append(tokensLine)
        if topModels:
            modelNamesWithCounts: list[tuple[str, int]] = [(modelName, int(count)) for modelName, count in topModels]
            lines.extend(self._renderFencedTopBlock(modelNamesWithCounts, "Top models:"))

        # Annotation for user-level filtering
        if payload.get("userFilterApplied"):
            lines.append("  (на уровне чата, не пользователя)")

        # STT stats from payload
        sttRows = payload["rows"].get("stt_request", [])
        if sttRows:
            sttAnalyzer = StatsAnalyzer(sttRows)

            totalSttRequests = sttAnalyzer.sumMetric("request_count")
            errorSttRequests = sttAnalyzer.sumMetric("is_error")
            totalAudioDurationMs = sttAnalyzer.sumMetric("audio_duration_ms")
            totalSttElapsedTime = sttAnalyzer.sumMetric("elapsed_time")

            lines.append(f"  **STT:** {self._formatCount(int(totalSttRequests))}")
            if errorSttRequests > 0:
                lines.append(f"    errors: {self._formatCount(int(errorSttRequests))}")
            if totalAudioDurationMs > 0:
                audioDurationSecs = totalAudioDurationMs / 1000.0
                lines.append(f"    audio: {self._formatDuration(audioDurationSecs, subMinuteDecimals=1)}")
            if totalSttRequests > 0:
                avgSttTime = totalSttElapsedTime / totalSttRequests
                lines.append(f"    avg time: {self._formatDuration(avgSttTime)}")

        return "\n".join(lines)

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
