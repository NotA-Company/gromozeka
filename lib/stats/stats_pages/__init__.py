"""Statistics page generator for Gromozeka.

Provides a CLI tool for generating self-contained HTML statistics pages from
raw aggregate row data. The generator reads a JSON payload from stdin and
outputs page metadata to stdout.

Usage (generate):
    echo '{"userId":"u123","chatId":"c456",...,"rows":{"message":[...]}}' | \\
        ./venv/bin/python3 -m lib.stats.stats_pages generate \\
        --output-dir /path/to/pages --base-url https://example.com/pages

Usage (delete):
    ./venv/bin/python3 -m lib.stats.stats_pages delete <pageId> \\
        --output-dir /path/to/pages

The generate command outputs single-line JSON to stdout:
    {"pageId": "<uuid-hex>", "url": "<filename or full-url>"}

The delete command outputs single-line JSON to stdout:
    {"deleted": 0 or 1}

Input payload (StatsPayload) structure:
    - userId, chatId, chatTitle, chatType, platform, period, periodType, generatedAt (required)
    - rows: dict[eventType -> list[StatsAggregateDict]] (required)
        Event types: "message", "command", "llm_tool_call", "llm_request", "stt_request"
    - chatList: list[ChatListEntry] (optional, private scope only)

The generator performs server-side grouping, time-series construction, and
inline SVG chart rendering. All dependencies are Python stdlib only.
"""

from .generator import ChatListEntry, StatsPageGenerator, StatsPayload
from .launcher import StatsCliError, StatsCliErrorReason, runCliCommand

__all__ = [
    "StatsPageGenerator",
    "StatsPayload",
    "ChatListEntry",
    "runCliCommand",
    "StatsCliError",
    "StatsCliErrorReason",
]
