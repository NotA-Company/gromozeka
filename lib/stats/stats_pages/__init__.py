"""Statistics page generator for Gromozeka.

Provides a module-invocable CLI for generating self-contained HTML
statistics pages and deleting them. The generator reads a stats view-model
from stdin and produces a self-contained static HTML page with inline CSS.

Entry points:
    generate: Read JSON from stdin, write HTML file, print {"id", "url"} to stdout
    delete: Delete a page by ID, print {"deleted": 0|1} to stdout

Used by StatsHandler via subprocess invocation; zero new runtime dependencies.
"""

from .generator import (
    ChatListEntry,
    CommandsSectionData,
    LlmSectionData,
    MessagesSectionData,
    StatsPageGenerator,
    StatsPayload,
    SttSectionData,
    ToolsSectionData,
)
from .launcher import StatsCliError, StatsCliErrorReason, runCliCommand

__all__ = [
    "StatsPageGenerator",
    "StatsPayload",
    "MessagesSectionData",
    "CommandsSectionData",
    "ToolsSectionData",
    "LlmSectionData",
    "SttSectionData",
    "ChatListEntry",
    "StatsCliError",
    "StatsCliErrorReason",
    "runCliCommand",
]
