"""Statistics page generator for Gromozeka.

Provides HTML generation from raw aggregate row data and page lifecycle
management. All dependencies are Python stdlib only (argparse, html, json,
uuid, pathlib). No external resources, no JS dependencies.

The generator accepts raw aggregate rows from the stat_aggregates table
and performs server-side grouping, time-series construction, and rendering
in pure Python. Inline SVG bar charts are rendered without external
dependencies.
"""

import argparse
import html
import json
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from lib.stats.types import StatsAggregateDict

# Compiled pattern for validating pageId (must be uuid4().hex format)
PAGE_ID_PATTERN = re.compile("^[0-9a-f]{32}$")


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


class StatsPayload(TypedDict):
    """Statistics payload for page generation (stdin JSON contract).

    This is the JSON structure the bot passes to the CLI generator via stdin.
    Contains metadata and raw aggregate rows keyed by eventType. The bot
    applies ONLY scope filters, granularity, range, and limit=10000; all
    grouping, time-series construction, and rendering happens server-side.

    Attributes:
        userId: User ID who requested the page.
        chatId: Chat ID the page is for.
        chatTitle: Chat title or name.
        chatType: Chat type ("private", "group", or "channel").
        platform: Platform name ("telegram" or "max").
        period: Period specifier (e.g., "7d", "6h", "2m", "all").
        periodType: Period granularity ("hourly", "daily", "monthly", or "total").
        generatedAt: ISO-8601 UTC timestamp of page generation.
        rows: Dictionary keyed by eventType containing raw aggregate rows.
            Keys: "message", "command", "llm_tool_call", "llm_request", "stt_request".
        chatList: For private chats, list of user's chats with message counts.
        chatListTotal: Total count of user's chats (for trailer display).
        truncatedEventTypes: List of event types that hit the 10000-row limit.
        userFilterApplied: Whether a user filter (--user) was applied by the requester.
    """

    userId: str
    chatId: str
    chatTitle: str
    chatType: str
    platform: str
    period: str
    periodType: str
    generatedAt: str
    rows: dict[str, list[StatsAggregateDict]]
    chatList: NotRequired[list[ChatListEntry]]
    chatListTotal: NotRequired[int]
    truncatedEventTypes: NotRequired[list[str]]
    userFilterApplied: NotRequired[bool]


class StatsPageGenerator:
    """Generates self-contained HTML statistics pages from raw aggregate rows.

    Reads a StatsPayload from JSON, performs server-side grouping and
    time-series construction, and produces a single static HTML file with
    inline CSS and inline SVG charts. No external dependencies, no CDN links,
    no JavaScript.

    Attributes:
        outputDir: Directory where generated pages are stored.
    """

    def __init__(self, outputDir: str | Path = ".") -> None:
        """Initialize the generator.

        Args:
            outputDir: Directory to store generated pages. Defaults to current
                directory. The directory will be created when generating pages.
        """
        self.outputDir = Path(outputDir)

    def generate(self, payload: StatsPayload, baseUrl: str | None = None) -> tuple[str, str]:
        """Generate an HTML page from the payload.

        Args:
            payload: Statistics payload with raw aggregate rows.
            baseUrl: Optional base URL for constructing full URLs. If provided,
                the returned URL will be baseUrl.rstrip("/") + "/" + filename.

        Returns:
            tuple[str, str]: (pageId, url) where pageId is the UUID filename stem
                and url is the full URL or bare filename depending on baseUrl.

        Raises:
            IOError: If the file cannot be written.
        """
        pageId = uuid.uuid4().hex
        filename = f"{pageId}.html"
        filePath = self.outputDir / filename

        htmlContent = self._renderHtml(payload)
        # Create parent directories if they don't exist
        self.outputDir.mkdir(parents=True, exist_ok=True)
        filePath.write_text(htmlContent, encoding="utf-8")

        # Construct URL based on baseUrl
        if baseUrl:
            url = f"{baseUrl.rstrip('/')}/{filename}"
        else:
            url = filename

        return pageId, url

    def delete(self, pageId: str) -> int:
        """Delete a page by ID.

        Args:
            pageId: UUID filename stem of the page to delete. Must match
                uuid4().hex format (32 hexadecimal characters).

        Returns:
            int: 1 if a file was deleted, 0 if no such file existed or
                if pageId failed validation.
        """
        # Validate pageId shape to prevent path traversal
        if not PAGE_ID_PATTERN.match(pageId):
            return 0

        filePath = self.outputDir / f"{pageId}.html"
        try:
            filePath.unlink()
            return 1
        except FileNotFoundError:
            return 0

    def _groupRowsByMetric(self, rows: list[StatsAggregateDict]) -> dict[str, float]:
        """Group rows by metricKey and sum metricValue.

        Args:
            rows: List of aggregate rows.

        Returns:
            Dictionary mapping metricKey to total sum.
        """
        grouped: dict[str, float] = defaultdict(float)
        for row in rows:
            grouped[row["metricKey"]] += row["metricValue"]
        return dict(grouped)

    def _shouldShowHonestyLine(
        self, eventType: str, rows: list[StatsAggregateDict], truncatedEventTypes: list[str]
    ) -> bool:
        """Check if the truncation honesty line should be shown for a section.

        The line appears when the eventType is explicitly in truncatedEventTypes.
        Trusts ONLY the flag from the payload; no fallback heuristics.

        Args:
            eventType: The event type for this section (e.g., "message", "command").
            rows: List of aggregate rows for this section (unused, kept for API compatibility).
            truncatedEventTypes: List of event types that hit the 10000-row limit.

        Returns:
            bool: True if honesty line should be shown, False otherwise.
        """
        return eventType in truncatedEventTypes

    def _buildTimeSeries(
        self, rows: list[StatsAggregateDict], metricKey: str, periodType: str
    ) -> list[tuple[str, float]]:
        """Build a time series from rows for a specific metric.

        Args:
            rows: List of aggregate rows.
            metricKey: The metric key to extract.
            periodType: Period granularity ("hourly", "daily", "monthly", "total").

        Returns:
            List of (periodStart, value) tuples sorted by periodStart.
            Empty list for "total" granularity or if no data.
        """
        if periodType == "total":
            # No time series for total granularity (single sentinel bucket)
            return []

        timeSeries: dict[str, float] = defaultdict(float)
        for row in rows:
            if row["metricKey"] == metricKey:
                timeSeries[row["periodStart"]] += row["metricValue"]

        # Sort by periodStart (ISO strings compare lexicographically)
        return sorted(timeSeries.items())

    def _renderInlineSvgChart(self, timeSeries: list[tuple[str, float]], maxBars: int = 24) -> str:
        """Render an inline SVG bar chart from time series data.

        Args:
            timeSeries: List of (periodStart, value) tuples.
            maxBars: Maximum number of bars to render (for hourly data).

        Returns:
            str: SVG markup with inline chart, optionally followed by a caption
                paragraph if the data was truncated. Empty string if no data.
        """
        if not timeSeries:
            return ""

        # Track truncation for caption
        truncated = len(timeSeries) > maxBars
        originalCount = len(timeSeries)

        # Limit bars for hourly data to avoid overcrowding
        if truncated:
            timeSeries = timeSeries[-maxBars:]

        # Find max value for scaling
        maxValue = max(value for _, value in timeSeries)
        if maxValue == 0:
            return ""

        # Chart dimensions
        width = 600
        height = 200
        barWidth = (width - 100) / len(timeSeries)  # Leave space for labels
        maxBarHeight = height - 40  # Leave space for axis labels

        # Build SVG
        svgParts = [
            f'<svg width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            'xmlns="http://www.w3.org/2000/svg">',
            '<rect width="100%" height="100%" fill="#f8f9fa"/>',  # Background
        ]

        # Draw bars
        for i, (periodStart, value) in enumerate(timeSeries):
            barHeight = (value / maxValue) * maxBarHeight if maxValue > 0 else 0
            x = 50 + i * barWidth
            y = maxBarHeight - barHeight + 20

            # Escape the value for display
            valueEscaped = html.escape(str(int(value)))

            svgParts.append(
                f'<rect x="{x}" y="{y}" width="{barWidth - 2}" '
                f'height="{barHeight}" fill="#3498db" '
                f'stroke="#2980b9" stroke-width="1"/>'
            )
            svgParts.append(
                f'<text x="{x + barWidth / 2}" y="{y - 5}" '
                f'font-size="10" text-anchor="middle" '
                f'fill="#2c3e50">{valueEscaped}</text>'
            )

        # X-axis labels (simplified - show first, middle, last)
        if len(timeSeries) >= 3:
            # Choose indices deterministically for even/odd counts
            indices = [0, round((len(timeSeries) - 1) / 2), len(timeSeries) - 1]
            for i, (periodStart, _) in enumerate([timeSeries[idx] for idx in indices]):
                x = 50 + indices[i] * barWidth + barWidth / 2  # Anchor at bar center
                # Extract just the time for display
                if "T" in periodStart:
                    label = periodStart.split("T")[1][:5]  # HH:MM
                else:
                    label = periodStart[:10]  # YYYY-MM-DD
                labelEscaped = html.escape(label)
                svgParts.append(
                    f'<text x="{x}" y="{height - 5}" '
                    f'font-size="9" text-anchor="middle" '
                    f'fill="#7f8c8d">{labelEscaped}</text>'
                )
        elif timeSeries:
            # Single point - show full timestamp
            periodStart, _ = timeSeries[0]
            if "T" in periodStart:
                label = periodStart.split("T")[1][:5]
            else:
                label = periodStart[:10]
            labelEscaped = html.escape(label)
            x = 50 + barWidth / 2
            svgParts.append(
                f'<text x="{x}" y="{height - 5}" font-size="9" '
                f'text-anchor="middle" fill="#7f8c8d">{labelEscaped}</text>'
            )

        svgParts.append("</svg>")

        svg = "\n".join(svgParts)

        # Add truncation caption if needed
        if truncated:
            remainingCount = originalCount - maxBars
            svg += f'\n        <p class="neutral" style="margin-top: 10px;">… и ещё {remainingCount}</p>\n'

        return svg

    def _renderHtml(self, payload: StatsPayload) -> str:
        """Render the complete HTML document.

        Args:
            payload: Statistics payload with raw aggregate rows.

        Returns:
            str: Complete HTML document with inline CSS.
        """
        # Extract payload fields
        userId = payload["userId"]
        chatId = payload["chatId"]
        chatTitle = payload["chatTitle"]
        chatType = payload["chatType"]
        platform = payload["platform"]
        period = payload["period"]
        periodType = payload["periodType"]
        generatedAt = payload["generatedAt"]

        rows = payload["rows"]
        truncatedEventTypes = payload.get("truncatedEventTypes", [])

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
        periodTypeEscaped = html.escape(periodType)

        # Build sections HTML from rows
        sectionsHtml = ""

        # Message section
        if "message" in rows:
            sectionsHtml += self._renderMessagesSection(rows["message"], periodType, truncatedEventTypes)

        # Command section
        if "command" in rows:
            sectionsHtml += self._renderCommandsSection(rows["command"], periodType, truncatedEventTypes)

        # Tool calls section
        if "llm_tool_call" in rows:
            sectionsHtml += self._renderToolsSection(rows["llm_tool_call"], periodType, truncatedEventTypes)

        # LLM section (llm_request + stt_request)
        llmRows = rows.get("llm_request", [])
        sttRows = rows.get("stt_request", [])
        userFilterApplied = payload.get("userFilterApplied", False)
        if llmRows or sttRows:
            sectionsHtml += self._renderLlmSection(llmRows, sttRows, periodType, truncatedEventTypes, userFilterApplied)

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
        h3 {{
            color: #2c3e50;
            margin-top: 20px;
            margin-bottom: 10px;
            font-size: 1.1em;
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
        svg {{
            display: block;
            margin: 20px 0;
            max-width: 100%;
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
                <span class="meta-label">Granularity:</span> {periodTypeEscaped}
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

    def _renderMessagesSection(
        self, rows: list[StatsAggregateDict], periodType: str, truncatedEventTypes: list[str]
    ) -> str:
        """Render the messages statistics section from raw rows.

        Args:
            rows: Raw aggregate rows for message events.
            periodType: Period granularity.
            truncatedEventTypes: List of event types that hit the 10000-row limit.

        Returns:
            str: HTML for the messages section.
        """
        # Group by metric
        metrics = self._groupRowsByMetric(rows)

        # Extract key metrics
        totalMessages = int(metrics.get("message_count", 0))
        totalLength = int(metrics.get("text_length", 0))

        # Group by sent label (direction)
        sentGroups: dict[str, float] = defaultdict(float)
        for row in rows:
            if row["metricKey"] == "message_count":
                sent = row["labels"].get("sent", "False")
                sentGroups[sent] += row["metricValue"]

        botMessages = int(sentGroups.get("True", 0))
        userMessages = int(sentGroups.get("False", 0))

        # Average message length (weighted by count)
        avgLength = 0.0
        if totalMessages > 0:
            avgLength = totalLength / totalMessages

        # Top users by message count (exclude bot rows)
        userRows = [row for row in rows if row["labels"].get("sent", "False") == "False"]
        topUsers = self._groupRowsByLabelValue(userRows, "message_count", "user_id", 5)
        topUsersHtml = self._renderTopList("Top Users by Messages", topUsers)

        # Top message types
        topTypes = self._groupRowsByLabelValue(rows, "message_count", "message_type", 5)
        topTypesHtml = self._renderTopList("Top Message Types", topTypes)

        # Time series chart
        timeSeries = self._buildTimeSeries(rows, "message_count", periodType)
        chartHtml = self._renderInlineSvgChart(timeSeries)

        # Honesty line
        honestyLine = ""
        if self._shouldShowHonestyLine("message", rows, truncatedEventTypes):
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>💬 Messages</h2>
            {honestyLine}
            {chartHtml}
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

    def _renderCommandsSection(
        self, rows: list[StatsAggregateDict], periodType: str, truncatedEventTypes: list[str]
    ) -> str:
        """Render the commands statistics section from raw rows.

        Args:
            rows: Raw aggregate rows for command events.
            periodType: Period granularity.
            truncatedEventTypes: List of event types that hit the 10000-row limit.

        Returns:
            str: HTML for the commands section.
        """
        # Group by metric
        metrics = self._groupRowsByMetric(rows)

        # Extract key metrics
        totalCommands = int(metrics.get("command_count", 0))
        errorCommands = int(metrics.get("is_error", 0))

        # Top commands by count
        topCommands = self._groupRowsByLabelValue(rows, "command_count", "commandName", 10)
        topCommandsHtml = self._renderTopList("Top Commands", topCommands)

        # Time series chart
        timeSeries = self._buildTimeSeries(rows, "command_count", periodType)
        chartHtml = self._renderInlineSvgChart(timeSeries)

        # Honesty line
        honestyLine = ""
        if self._shouldShowHonestyLine("command", rows, truncatedEventTypes):
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>🔧 Commands</h2>
            {honestyLine}
            {chartHtml}
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

    def _renderToolsSection(
        self, rows: list[StatsAggregateDict], periodType: str, truncatedEventTypes: list[str]
    ) -> str:
        """Render the tools statistics section from raw rows.

        Args:
            rows: Raw aggregate rows for llm_tool_call events.
            periodType: Period granularity.
            truncatedEventTypes: List of event types that hit the 10000-row limit.

        Returns:
            str: HTML for the tools section.
        """
        # Group by metric
        metrics = self._groupRowsByMetric(rows)

        # Extract key metrics
        totalCalls = int(metrics.get("tool_call_count", 0))
        errorCalls = int(metrics.get("is_error", 0))
        totalElapsed = metrics.get("elapsed_time", 0)

        # Average elapsed time (weighted by count)
        avgElapsed = 0.0
        if totalCalls > 0:
            avgElapsed = totalElapsed / totalCalls

        # Top tools by count
        topTools = self._groupRowsByLabelValue(rows, "tool_call_count", "toolName", 10)
        topToolsHtml = self._renderTopList("Top Tools", topTools)

        # Time series chart
        timeSeries = self._buildTimeSeries(rows, "tool_call_count", periodType)
        chartHtml = self._renderInlineSvgChart(timeSeries)

        # Honesty line
        honestyLine = ""
        if self._shouldShowHonestyLine("llm_tool_call", rows, truncatedEventTypes):
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        return f"""        <div class="section">
            <h2>🛠️ Tools</h2>
            {honestyLine}
            {chartHtml}
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

    def _renderLlmSection(
        self,
        llmRows: list[StatsAggregateDict],
        sttRows: list[StatsAggregateDict],
        periodType: str,
        truncatedEventTypes: list[str],
        userFilterApplied: bool = False,
    ) -> str:
        """Render the LLM statistics section from raw rows.

        Args:
            llmRows: Raw aggregate rows for llm_request events.
            sttRows: Raw aggregate rows for stt_request events.
            periodType: Period granularity.
            truncatedEventTypes: List of event types that hit the 10000-row limit.
            userFilterApplied: Whether a user filter was applied (for annotation).

        Returns:
            str: HTML for the LLM section.
        """
        # Group LLM metrics
        llmMetrics = self._groupRowsByMetric(llmRows)

        # Extract key LLM metrics
        totalRequests = int(llmMetrics.get("request_count", 0))
        errorRequests = int(llmMetrics.get("is_error", 0))
        inputTokens = int(llmMetrics.get("input_tokens", 0))
        outputTokens = int(llmMetrics.get("output_tokens", 0))
        totalTokens = inputTokens + outputTokens
        totalElapsed = llmMetrics.get("elapsed_time", 0)
        toolCallsCount = int(llmMetrics.get("tool_calls_count", 0))

        # Optional provider-reported metrics: show "n/a" when no model in the
        # period ever reported them (metric key absent from aggregates).
        hasCachedTokens = "cached_input_tokens" in llmMetrics
        cachedTokensValue = self._formatNumber(int(llmMetrics.get("cached_input_tokens", 0)))
        cachedTokensCell = cachedTokensValue if hasCachedTokens else "n/a"
        hasReasoningTokens = "reasoning_tokens" in llmMetrics
        reasoningTokensValue = self._formatNumber(int(llmMetrics.get("reasoning_tokens", 0)))
        reasoningTokensCell = reasoningTokensValue if hasReasoningTokens else "n/a"
        hasCost = "cost" in llmMetrics
        costCell = f"${llmMetrics.get('cost', 0):,.6f}" if hasCost else "n/a"

        # Average elapsed time (weighted by count)
        avgElapsed = 0.0
        if totalRequests > 0:
            avgElapsed = totalElapsed / totalRequests

        # Top models by count
        topModels = self._groupRowsByLabelValue(llmRows, "request_count", "modelName", 5)
        topModelsHtml = self._renderTopList("Top Models", topModels)

        # Top providers by count
        topProviders = self._groupRowsByLabelValue(llmRows, "request_count", "provider", 5)
        topProvidersHtml = self._renderTopList("Top Providers", topProviders)

        # Time series chart
        timeSeries = self._buildTimeSeries(llmRows, "request_count", periodType)
        chartHtml = self._renderInlineSvgChart(timeSeries)

        # Honesty line for LLM
        honestyLine = ""
        if self._shouldShowHonestyLine("llm_request", llmRows, truncatedEventTypes):
            honestyLine = '<p class="neutral">⚠ Результаты могут быть неполными (достигнут лимит запроса)</p>\n'

        # User filter annotation (matches reply text pattern)
        userFilterAnnotation = ""
        if userFilterApplied:
            userFilterAnnotation = '<p class="neutral">на уровне чата, не пользователя</p>\n'

        # STT subsection
        sttHtml = ""
        if sttRows:
            sttMetrics = self._groupRowsByMetric(sttRows)

            sttTotal = int(sttMetrics.get("request_count", 0))
            sttErrors = int(sttMetrics.get("is_error", 0))
            sttAudioDuration = sttMetrics.get("audio_duration_ms", 0) / 1000.0  # Convert ms to seconds

            # STT honesty line
            sttHonestyLine = ""
            if self._shouldShowHonestyLine("stt_request", sttRows, truncatedEventTypes):
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

        return f"""        <div class="section">
            <h2>🧠 LLM</h2>
            {honestyLine}
            <p class="neutral">
                Note: LLM counts cover interactive generation only (embeddings
                and background requests excluded).
            </p>
            {userFilterAnnotation}
            {chartHtml}
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
                    <td>Cached Input Tokens (subset of input)</td>
                    <td class="metric">{cachedTokensCell}</td>
                </tr>
                <tr>
                    <td>Reasoning Tokens (subset of output)</td>
                    <td class="metric">{reasoningTokensCell}</td>
                </tr>
                <tr>
                    <td>Reported Cost (USD)</td>
                    <td class="metric">{costCell}</td>
                </tr>
                <tr>
                    <td>Tool Calls</td>
                    <td class="metric">{self._formatNumber(toolCallsCount)}</td>
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

    def _groupRowsByLabelValue(
        self, rows: list[StatsAggregateDict], metricKey: str, labelKey: str, topN: int
    ) -> list[tuple[str, float]]:
        """Group rows by a label value and sum a metric for each group.

        Args:
            rows: List of aggregate rows.
            metricKey: The metric key to sum.
            labelKey: The label key to group by.
            topN: Maximum number of top items to return.

        Returns:
            List of (labelValue, sum) tuples sorted by sum descending.
        """
        groups: dict[str, float] = defaultdict(float)
        for row in rows:
            if row["metricKey"] == metricKey:
                labelValue = row["labels"].get(labelKey, "")
                groups[labelValue] += row["metricValue"]

        # Sort by sum descending and take top N
        sortedGroups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
        return sortedGroups[:topN]

    def _renderChatList(self, chatList: list[ChatListEntry]) -> str:
        """Render the user's chat list (private scope).

        Args:
            chatList: List of chat entries with chatId, title, and
                messagesCount fields.

        Returns:
            str: HTML for the chat list table.
        """
        rows = ""
        for chat in chatList:
            chatId = chat["chatId"]
            title = chat["title"]
            messagesCount = chat["messagesCount"]

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
                    <td class="metric">{self._formatNumber(value, decimals=0)}</td>
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
            str: Formatted number string with thousands separators.
        """
        if isinstance(value, float):
            return f"{value:,.{decimals}f}"
        return f"{value:,}"


def readPayload() -> StatsPayload:
    """Read and parse JSON payload from stdin.

    Returns:
        StatsPayload: Parsed statistics payload.

    Raises:
        ValueError: If stdin is not valid JSON, payload is not a dict,
            or required fields are missing.
    """
    try:
        payloadJson = sys.stdin.read()
        payload = json.loads(payloadJson)

        # Validate payload is a dict
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")

        # Validate required meta fields
        requiredFields = [
            "userId",
            "chatId",
            "chatTitle",
            "chatType",
            "platform",
            "period",
            "periodType",
            "generatedAt",
            "rows",
        ]
        for field in requiredFields:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")

        return cast(StatsPayload, payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON on stdin: {e}") from e


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
        pageId, url = generator.generate(payload, baseUrl=args.baseUrl)

        # Warn if no baseUrl was provided
        if not args.baseUrl:
            print("WARNING: --base-url not provided; generated URL is a bare filename", file=sys.stderr)

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


def buildParser() -> argparse.ArgumentParser:
    """Build and return the argparse parser for the stats-pages CLI.

    Returns:
        argparse.ArgumentParser: Configured parser for stats-pages commands.
    """
    parser = argparse.ArgumentParser(
        description="Generate and delete statistics pages for Gromozeka.",
        prog="python -m lib.stats.stats_pages",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    # Generate command
    generateParser = subparsers.add_parser("generate", help="Generate a statistics page from stdin JSON")
    generateParser.add_argument(
        "--base-url",
        dest="baseUrl",
        help="Base URL for constructing full URLs (e.g., https://example.com/pages)",
        default=None,
        type=str,
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

    return parser


def main() -> int:
    """Main entry point for the stats-pages CLI.

    Returns:
        int: Exit code (0 for success, non-zero for failure).
    """
    parser = buildParser()
    args = parser.parse_args()

    if args.command == "generate":
        return handleGenerate(args)
    elif args.command == "delete":
        return handleDelete(args)

    # Unreachable: argparse required=True ensures a valid command
    return 1
