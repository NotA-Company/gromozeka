"""Statistics page generator for Gromozeka.

Provides HTML generation from stats view-model JSON and page lifecycle
management. All dependencies are Python stdlib only (argparse, html, json,
uuid, pathlib). No external resources, no JS dependencies.
"""

import argparse
import html
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NotRequired, TypedDict


class StatsPayload(TypedDict):
    """Statistics view-model payload for page generation.

    This is the JSON structure the bot passes to the CLI generator via stdin.
    Contains metadata and section-level statistics for rendering.

    Attributes:
        userId: User ID who requested the page.
        chatId: Chat ID the page is for.
        chatTitle: Chat title or name.
        chatType: Chat type ("private", "group", or "channel").
        platform: Platform name ("telegram" or "max").
        period: Period specifier ("1d", "7d", "30d", or "all").
        generatedAt: ISO-8601 UTC timestamp of page generation.
        sections: Dictionary containing statistics sections (messages, commands,
            tools, llm, stt). Each section contains stats for that event type.
        chatList: For private chats, list of user's chats with message counts.
    """

    userId: str
    chatId: str
    chatTitle: str
    chatType: str
    platform: str
    period: str
    generatedAt: str
    sections: dict[str, dict[str, Any]]
    chatList: NotRequired[list[dict[str, Any]]]


class MessagesSectionData(TypedDict):
    """Structured data for the messages section.

    Attributes:
        totalMessages: Total message count.
        totalLength: Total character count across all messages.
        userMessages: Count of messages sent by users.
        botMessages: Count of messages sent by the bot.
        historyMessages: Count of messages from before stats was enabled.
        avgLength: Average message length in characters.
        topUsers: Top 3 users by message count as [userId, count] pairs.
        topTypes: Top 3 message types by count as [type, count] pairs.
        possiblyIncomplete: Whether the query hit the 10k row limit.
    """

    totalMessages: int
    totalLength: int
    userMessages: int
    botMessages: int
    historyMessages: int
    avgLength: float
    topUsers: list[list[int | str]]
    topTypes: list[list[str | int]]
    possiblyIncomplete: NotRequired[bool]


class CommandsSectionData(TypedDict):
    """Structured data for the commands section.

    Attributes:
        totalCommands: Total command count.
        errorCommands: Count of commands that errored.
        totalElapsed: Total elapsed time in seconds.
        avgElapsed: Average elapsed time in seconds.
        topCommands: Top 3 commands by count as [commandName, count] pairs.
        possiblyIncomplete: Whether the query hit the 10k row limit.
    """

    totalCommands: int
    errorCommands: int
    totalElapsed: float
    avgElapsed: float
    topCommands: list[list[str | int]]
    possiblyIncomplete: NotRequired[bool]


class ToolsSectionData(TypedDict):
    """Structured data for the tools section.

    Attributes:
        totalCalls: Total tool call count.
        errorCalls: Count of tool calls that errored.
        totalElapsed: Total elapsed time in seconds.
        avgElapsed: Average elapsed time in seconds.
        topTools: Top 3 tools by count as [toolName, count] pairs.
        possiblyIncomplete: Whether the query hit the 10k row limit.
    """

    totalCalls: int
    errorCalls: int
    totalElapsed: float
    avgElapsed: float
    topTools: list[list[str | int]]
    possiblyIncomplete: NotRequired[bool]


class SttSectionData(TypedDict):
    """Structured data for the STT (speech-to-text) subsection.

    Attributes:
        totalRequests: Total STT request count.
        errorRequests: Count of STT requests that errored.
        totalAudioDuration: Total audio duration in seconds.
        totalElapsed: Total elapsed time in seconds.
        avgElapsed: Average elapsed time in seconds.
        topProviders: Top 3 providers by count as [provider, count] pairs.
        possiblyIncomplete: Whether the query hit the 10k row limit.
    """

    totalRequests: int
    errorRequests: int
    totalAudioDuration: float
    totalElapsed: float
    avgElapsed: float
    topProviders: list[list[str | int]]
    possiblyIncomplete: NotRequired[bool]


class LlmSectionData(TypedDict):
    """Structured data for the LLM section (including STT subsection).

    Attributes:
        totalRequests: Total LLM request count.
        errorRequests: Count of LLM requests that errored.
        inputTokens: Total input tokens.
        outputTokens: Total output tokens.
        totalTokens: Total tokens (input + output).
        totalElapsed: Total elapsed time in seconds.
        avgElapsed: Average elapsed time in seconds.
        topModels: Top 3 models by count as [modelName, count] pairs.
        topProviders: Top 3 providers by count as [provider, count] pairs.
        stt: STT subsection data (speech-to-text stats).
        possiblyIncomplete: Whether the query hit the 10k row limit.
    """

    totalRequests: int
    errorRequests: int
    inputTokens: int
    outputTokens: int
    totalTokens: int
    totalElapsed: float
    avgElapsed: float
    topModels: list[list[str | int]]
    topProviders: list[list[str | int]]
    stt: NotRequired[SttSectionData]
    possiblyIncomplete: NotRequired[bool]


class ChatListEntry(TypedDict):
    """Entry in the user's chat list (private scope).

    Attributes:
        chatId: Chat ID.
        title: Chat title or name.
        messagesCount: The user's message count in this chat.
    """

    chatId: int
    title: str
    messagesCount: int


class StatsPageGenerator:
    """Generates self-contained HTML statistics pages.

    Reads a StatsPayload from JSON and produces a single static HTML file with
    inline CSS. No external dependencies, no CDN links, no JavaScript.

    Attributes:
        outputDir: Directory where generated pages are stored.
    """

    def __init__(self, outputDir: str | Path = ".") -> None:
        """Initialize the generator.

        Args:
            outputDir: Directory to store generated pages. Defaults to current
                directory.
        """
        self.outputDir = Path(outputDir)
        self.outputDir.mkdir(parents=True, exist_ok=True)

    def generate(self, payload: StatsPayload) -> tuple[str, str]:
        """Generate an HTML page from the payload.

        Args:
            payload: Statistics view-model payload from stdin.

        Returns:
            tuple[str, str]: (pageId, relativeUrl) where pageId is the UUID
                filename stem and relativeUrl is the filename with .html
                extension.

        Raises:
            IOError: If the file cannot be written.
        """
        pageId = uuid.uuid4().hex
        filename = f"{pageId}.html"
        filePath = self.outputDir / filename

        htmlContent = self._renderHtml(payload)
        filePath.write_text(htmlContent, encoding="utf-8")

        return pageId, filename

    def delete(self, pageId: str) -> int:
        """Delete a page by ID.

        Args:
            pageId: UUID filename stem of the page to delete.

        Returns:
            int: 1 if a file was deleted, 0 if no such file existed.
        """
        filePath = self.outputDir / f"{pageId}.html"
        if filePath.exists():
            filePath.unlink()
            return 1
        return 0

    def _renderHtml(self, payload: StatsPayload) -> str:
        """Render the complete HTML document.

        Args:
            payload: Statistics view-model payload.

        Returns:
            str: Complete HTML document with inline CSS.
        """
        # Extract payload fields with defaults
        userId = payload.get("userId", "unknown")
        chatId = payload.get("chatId", "unknown")
        chatTitle = payload.get("chatTitle", "Unknown Chat")
        chatType = payload.get("chatType", "unknown")
        platform = payload.get("platform", "unknown")
        period = payload.get("period", "unknown")
        generatedAt = payload.get("generatedAt", datetime.now(timezone.utc).isoformat())

        # Parse generated_at for display
        try:
            generatedTs = datetime.fromisoformat(generatedAt)
            # Normalize to UTC before formatting
            generatedTsUtc = generatedTs.astimezone(timezone.utc)
            generatedFormatted = html.escape(generatedTsUtc.strftime("%Y-%m-%d %H:%M:%S UTC"))
        except Exception:
            # Fallback: escape the raw generatedAt string
            generatedFormatted = html.escape(generatedAt)

        # Escape all text content
        chatTitleEscaped = html.escape(chatTitle)
        userIdEscaped = html.escape(userId)
        chatIdEscaped = html.escape(chatId)
        platformEscaped = html.escape(platform)
        periodEscaped = html.escape(period)
        chatTypeEscaped = html.escape(chatType)

        # Build sections HTML
        sectionsHtml = ""
        sections = payload.get("sections", {})

        # Messages section
        if "messages" in sections:
            sectionsHtml += self._renderMessagesSection(sections["messages"])

        # Commands section
        if "commands" in sections:
            sectionsHtml += self._renderCommandsSection(sections["commands"])

        # Tools section
        if "tools" in sections:
            sectionsHtml += self._renderToolsSection(sections["tools"])

        # LLM section (includes STT per D6)
        if "llm" in sections:
            sectionsHtml += self._renderLlmSection(sections["llm"])
        elif "stt" in sections:
            sectionsHtml += self._renderSttSection(sections["stt"])

        # Chat list for private chats
        chatListHtml = ""
        chatList = payload.get("chatList", [])
        if chatList:
            chatListHtml = self._renderChatList(chatList)

        # Build the complete HTML
        htmlTemplate = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Statistics: {chatTitleEscaped}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica,
                Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
            background-color: #f5f5f5;
        }}
        .container {{
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            border-left: 4px solid #3498db;
            padding-left: 10px;
        }}
        .meta {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 25px;
            font-size: 0.95em;
        }}
        .meta-row {{
            margin: 5px 0;
        }}
        .meta-label {{
            font-weight: 600;
            color: #7f8c8d;
            display: inline-block;
            min-width: 120px;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
            background-color: white;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: 600;
        }}
        tr:hover {{
            background-color: #f8f9fa;
        }}
        .metric {{
            font-weight: 600;
        }}
        .positive {{
            color: #27ae60;
        }}
        .neutral {{
            color: #7f8c8d;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
            font-size: 0.85em;
            color: #7f8c8d;
        }}
        .utc {{
            color: #e67e22;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Chat Statistics</h1>

        <div class="meta">
            <div class="meta-row">
                <span class="meta-label">Chat:</span> {chatTitleEscaped}
                (#{chatIdEscaped})
            </div>
            <div class="meta-row"><span class="meta-label">Type:</span> {chatTypeEscaped}</div>
            <div class="meta-row">
                <span class="meta-label">Platform:</span> {platformEscaped}
            </div>
            <div class="meta-row">
                <span class="meta-label">Period:</span> {periodEscaped}
                <span class="utc">(UTC)</span>
            </div>
            <div class="meta-row">
                <span class="meta-label">Generated by:</span> {userIdEscaped}
            </div>
            <div class="meta-row">
                <span class="meta-label">Generated at:</span> {generatedFormatted}
            </div>
        </div>

        {sectionsHtml}

        {chatListHtml}

        <div class="footer">
            <p>
                Page generated by Gromozeka Stats Handler. This page expires after
                the configured TTL and is deleted automatically.
            </p>
        </div>
    </div>
</body>
</html>"""

        return htmlTemplate

    def _renderMessagesSection(self, sectionData: dict[str, Any]) -> str:
        """Render the messages statistics section.

        Args:
            sectionData: Messages section data from the payload.

        Returns:
            str: HTML for the messages section.
        """
        totalMessages = sectionData.get("totalMessages", 0)
        totalLength = sectionData.get("totalLength", 0)
        userMessages = sectionData.get("userMessages", 0)
        botMessages = sectionData.get("botMessages", 0)
        historyMessages = sectionData.get("historyMessages", 0)
        avgLength = sectionData.get("avgLength", 0.0)
        topUsers = sectionData.get("topUsers", [])
        topTypes = sectionData.get("topTypes", [])
        possiblyIncomplete = sectionData.get("possiblyIncomplete", False)

        topUsersHtml = self._renderTopList("Top Users by Messages", topUsers)
        topTypesHtml = self._renderTopList("Top Message Types", topTypes)

        honestyLine = ""
        if possiblyIncomplete:
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>💬 Messages</h2>
            {honestyLine}
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Total Messages</td>
                    <td class="metric">{self._formatNumber(totalMessages)}</td>
                </tr>
                <tr>
                    <td>User Messages</td>
                    <td class="metric positive">{self._formatNumber(userMessages)}</td>
                </tr>
                <tr>
                    <td>Bot Messages</td>
                    <td class="metric neutral">{self._formatNumber(botMessages)}</td>
                </tr>
                <tr>
                    <td>History (before stats enabled)</td>
                    <td class="metric neutral">{self._formatNumber(historyMessages)}</td>
                </tr>
                <tr>
                    <td>Total Characters</td>
                    <td class="metric">{self._formatNumber(totalLength)}</td>
                </tr>
                <tr>
                    <td>Average Message Length</td>
                    <td class="metric">{self._formatNumber(avgLength, decimals=2)}</td>
                </tr>
            </table>
            {topUsersHtml}
            {topTypesHtml}
        </div>
"""

    def _renderCommandsSection(self, sectionData: dict[str, Any]) -> str:
        """Render the commands statistics section.

        Args:
            sectionData: Commands section data from the payload.

        Returns:
            str: HTML for the commands section.
        """
        totalCommands = sectionData.get("totalCommands", 0)
        errorCommands = sectionData.get("errorCommands", 0)
        topCommands = sectionData.get("topCommands", [])
        possiblyIncomplete = sectionData.get("possiblyIncomplete", False)

        topCommandsHtml = self._renderTopList("Top Commands", topCommands)

        honestyLine = ""
        if possiblyIncomplete:
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>🔧 Commands</h2>
            {honestyLine}
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Total Commands</td>
                    <td class="metric">{self._formatNumber(totalCommands)}</td>
                </tr>
                <tr>
                    <td>Successful</td>
                    <td class="metric positive">{self._formatNumber(totalCommands - errorCommands)}</td>
                </tr>
                <tr>
                    <td>Errors</td>
                    <td class="metric neutral">{self._formatNumber(errorCommands)}</td>
                </tr>
            </table>
            {topCommandsHtml}
        </div>
"""

    def _renderToolsSection(self, sectionData: dict[str, Any]) -> str:
        """Render the tools statistics section.

        Args:
            sectionData: Tools section data from the payload.

        Returns:
            str: HTML for the tools section.
        """
        totalCalls = sectionData.get("totalCalls", 0)
        errorCalls = sectionData.get("errorCalls", 0)
        totalElapsed = sectionData.get("totalElapsed", 0.0)
        avgElapsed = sectionData.get("avgElapsed", 0.0)
        topTools = sectionData.get("topTools", [])
        possiblyIncomplete = sectionData.get("possiblyIncomplete", False)

        topToolsHtml = self._renderTopList("Top Tools", topTools)

        honestyLine = ""
        if possiblyIncomplete:
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>🛠️ Tools</h2>
            {honestyLine}
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Total Tool Calls</td>
                    <td class="metric">{self._formatNumber(totalCalls)}</td>
                </tr>
                <tr>
                    <td>Successful</td>
                    <td class="metric positive">{self._formatNumber(totalCalls - errorCalls)}</td>
                </tr>
                <tr>
                    <td>Errors</td>
                    <td class="metric neutral">{self._formatNumber(errorCalls)}</td>
                </tr>
                <tr>
                    <td>Total Time</td>
                    <td class="metric">{self._formatNumber(totalElapsed, decimals=2)}s</td>
                </tr>
                <tr>
                    <td>Average Time</td>
                    <td class="metric">{self._formatNumber(avgElapsed, decimals=2)}s</td>
                </tr>
            </table>
            {topToolsHtml}
        </div>
"""

    def _renderLlmSection(self, sectionData: dict[str, Any]) -> str:
        """Render the LLM statistics section.

        Args:
            sectionData: LLM section data from the payload.

        Returns:
            str: HTML for the LLM section.
        """
        totalRequests = sectionData.get("totalRequests", 0)
        errorRequests = sectionData.get("errorRequests", 0)
        inputTokens = sectionData.get("inputTokens", 0)
        outputTokens = sectionData.get("outputTokens", 0)
        totalTokens = sectionData.get("totalTokens", 0)
        totalElapsed = sectionData.get("totalElapsed", 0.0)
        avgElapsed = sectionData.get("avgElapsed", 0.0)
        topModels = sectionData.get("topModels", [])
        topProviders = sectionData.get("topProviders", [])
        possiblyIncomplete = sectionData.get("possiblyIncomplete", False)

        # STT subsection (folded into LLM per D6)
        sttHtml = ""
        sttData = sectionData.get("stt", {})
        if sttData:
            sttTotal = sttData.get("totalRequests", 0)
            sttErrors = sttData.get("errorRequests", 0)
            sttAudioDuration = sttData.get("totalAudioDuration", 0.0)
            sttPossiblyIncomplete = sttData.get("possiblyIncomplete", False)

            sttHonestyLine = ""
            if sttPossiblyIncomplete:
                sttHonestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

            sttHtml = f"""
            <h3>🎤 Speech-to-Text</h3>
            {sttHonestyLine}
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Total Requests</td>
                    <td class="metric">{self._formatNumber(sttTotal)}</td>
                </tr>
                <tr>
                    <td>Successful</td>
                    <td class="metric positive">{self._formatNumber(sttTotal - sttErrors)}</td>
                </tr>
                <tr>
                    <td>Errors</td>
                    <td class="metric neutral">{self._formatNumber(sttErrors)}</td>
                </tr>
                <tr>
                    <td>Total Audio Duration</td>
                    <td class="metric">
                        {self._formatNumber(sttAudioDuration, decimals=2)}s
                    </td>
                </tr>
            </table>
"""

        topModelsHtml = self._renderTopList("Top Models", topModels)
        topProvidersHtml = self._renderTopList("Top Providers", topProviders)

        honestyLine = ""
        if possiblyIncomplete:
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>🧠 LLM</h2>
            {honestyLine}
            <p class="neutral">
                Note: LLM counts cover interactive generation only (embeddings
                and background requests excluded).
            </p>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Total Requests</td>
                    <td class="metric">{self._formatNumber(totalRequests)}</td>
                </tr>
                <tr>
                    <td>Successful</td>
                    <td class="metric positive">{self._formatNumber(totalRequests - errorRequests)}</td>
                </tr>
                <tr>
                    <td>Errors</td>
                    <td class="metric neutral">{self._formatNumber(errorRequests)}</td>
                </tr>
                <tr>
                    <td>Input Tokens</td>
                    <td class="metric">{self._formatNumber(inputTokens)}</td>
                </tr>
                <tr>
                    <td>Output Tokens</td>
                    <td class="metric">{self._formatNumber(outputTokens)}</td>
                </tr>
                <tr>
                    <td>Total Tokens</td>
                    <td class="metric">{self._formatNumber(totalTokens)}</td>
                </tr>
                <tr>
                    <td>Total Time</td>
                    <td class="metric">{self._formatNumber(totalElapsed, decimals=2)}s</td>
                </tr>
                <tr>
                    <td>Average Time</td>
                    <td class="metric">{self._formatNumber(avgElapsed, decimals=2)}s</td>
                </tr>
            </table>
            {topModelsHtml}
            {topProvidersHtml}
            {sttHtml}
        </div>
"""

    def _renderSttSection(self, sectionData: dict[str, Any]) -> str:
        """Render a standalone STT statistics section.

        Args:
            sectionData: STT section data from the payload.

        Returns:
            str: HTML for the STT section.
        """
        totalRequests = sectionData.get("totalRequests", 0)
        errorRequests = sectionData.get("errorRequests", 0)
        totalAudioDuration = sectionData.get("totalAudioDuration", 0.0)
        totalElapsed = sectionData.get("totalElapsed", 0.0)
        avgElapsed = sectionData.get("avgElapsed", 0.0)
        topProviders = sectionData.get("topProviders", [])

        topProvidersHtml = self._renderTopList("Top Providers", topProviders)

        return f"""        <div class="section">
            <h2>🎤 Speech-to-Text</h2>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Total Requests</td>
                    <td class="metric">{self._formatNumber(totalRequests)}</td>
                </tr>
                <tr>
                    <td>Successful</td>
                    <td class="metric positive">{self._formatNumber(totalRequests - errorRequests)}</td>
                </tr>
                <tr>
                    <td>Errors</td>
                    <td class="metric neutral">{self._formatNumber(errorRequests)}</td>
                </tr>
                <tr>
                    <td>Total Audio Duration</td>
                    <td class="metric">{self._formatNumber(totalAudioDuration, decimals=2)}s</td>
                </tr>
                <tr>
                    <td>Total Time</td>
                    <td class="metric">{self._formatNumber(totalElapsed, decimals=2)}s</td>
                </tr>
                <tr>
                    <td>Average Time</td>
                    <td class="metric">{self._formatNumber(avgElapsed, decimals=2)}s</td>
                </tr>
            </table>
            {topProvidersHtml}
        </div>
"""

    def _renderChatList(self, chatList: list[dict[str, Any]]) -> str:
        """Render the user's chat list (private scope).

        Args:
            chatList: List of chat dictionaries with chatId, title, and
                messagesCount fields.

        Returns:
            str: HTML for the chat list table.
        """
        rows = ""
        for chat in chatList:
            chatId = chat.get("chatId", "unknown")
            title = chat.get("title", "Unknown")
            messagesCount = chat.get("messagesCount", 0)

            chatIdEscaped = html.escape(str(chatId))
            titleEscaped = html.escape(title)

            rows += f"""                <tr>
                    <td>{titleEscaped}</td>
                    <td>#{chatIdEscaped}</td>
                    <td class="metric">
                        {self._formatNumber(messagesCount)}
                    </td>
                </tr>
"""

        return f"""        <div class="section">
            <h2>📋 Your Chats</h2>
            <table>
                <tr>
                    <th>Chat</th>
                    <th>ID</th>
                    <th>Your Messages</th>
                </tr>
{rows}
            </table>
        </div>
"""

    def _renderTopList(self, title: str, items: list[tuple[str, float]]) -> str:
        """Render a top-N list table.

        Args:
            title: Section title.
            items: List of (name, value) tuples, sorted by value descending.

        Returns:
            str: HTML table for the top-N list, or empty string if no items.
        """
        if not items:
            return ""

        rows = ""
        for name, value in items:
            nameEscaped = html.escape(name)
            rows += f"""                <tr>
                    <td>{nameEscaped}</td>
                    <td class="metric">{self._formatNumber(value, decimals=2)}</td>
                </tr>
"""

        return f"""            <h3>{html.escape(title)}</h3>
            <table>
                <tr>
                    <th>Name</th>
                    <th>Value</th>
                </tr>
{rows}
            </table>
"""

    def _formatNumber(self, value: int | float, decimals: int = 0) -> str:
        """Format a number for display.

        Args:
            value: Number to format.
            decimals: Number of decimal places for floats.

        Returns:
            str: Formatted number string.
        """
        if isinstance(value, float):
            return f"{value:.{decimals}f}"
        return f"{value:,}"


def readPayload() -> StatsPayload:
    """Read and parse JSON payload from stdin.

    Returns:
        StatsPayload: Parsed statistics payload.

    Raises:
        ValueError: If stdin is not valid JSON, required fields are missing,
            or payload structure is invalid.
    """
    try:
        payloadJson = sys.stdin.read()
        payload = json.loads(payloadJson)

        # Validate required fields
        requiredFields = ["userId", "chatId", "chatTitle", "chatType", "platform", "period", "generatedAt"]
        for field in requiredFields:
            if field not in payload:
                raise KeyError(f"Missing required field: {field}")

        return StatsPayload(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON on stdin: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to parse payload: {e}") from e


def handleGenerate(args: argparse.Namespace) -> int:
    """Handle the generate command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        int: Exit code (0 for success, non-zero for failure).
    """
    try:
        payload = readPayload()
        generator = StatsPageGenerator(outputDir=args.outputDir)
        pageId, url = generator.generate(payload)

        # Output the result JSON to stdout
        result = {"pageId": pageId, "url": url}
        print(json.dumps(result))

        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def handleDelete(args: argparse.Namespace) -> int:
    """Handle the delete command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        int: Exit code (0 for success, non-zero for failure).
    """
    try:
        generator = StatsPageGenerator(outputDir=args.outputDir)
        deleted = generator.delete(args.pageId)

        result = {"deleted": deleted}
        print(json.dumps(result))

        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """Main entry point for the stats-pages CLI.

    Returns:
        int: Exit code (0 for success, non-zero for failure).
    """
    parser = argparse.ArgumentParser(
        description="Generate and delete statistics pages for Gromozeka.",
        prog="python -m lib.stats.stats_pages",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    # Generate command
    generateParser = subparsers.add_parser("generate", help="Generate a statistics page from stdin JSON")
    generateParser.add_argument(
        "--user-id",
        dest="userId",
        help="User ID (for metadata only, not used in payload)",
        default=None,
    )
    generateParser.add_argument(
        "--chat-id",
        dest="chatId",
        help="Chat ID (for metadata only, not used in payload)",
        default=None,
    )
    generateParser.add_argument(
        "--platform",
        dest="platform",
        help="Platform name (for metadata only, not used in payload)",
        default=None,
    )
    generateParser.add_argument(
        "--output-dir",
        dest="outputDir",
        help="Output directory for generated HTML files",
        default=".",
        type=str,
    )

    # Delete command
    deleteParser = subparsers.add_parser("delete", help="Delete a statistics page by ID")
    deleteParser.add_argument(
        "pageId",
        help="Page ID (UUID filename stem)",
        type=str,
    )
    deleteParser.add_argument(
        "--output-dir",
        dest="outputDir",
        help="Directory containing the page files",
        default=".",
        type=str,
    )

    args = parser.parse_args()

    if args.command == "generate":
        return handleGenerate(args)
    elif args.command == "delete":
        return handleDelete(args)

    # Unreachable: argparse required=True ensures a valid command
    return 1
