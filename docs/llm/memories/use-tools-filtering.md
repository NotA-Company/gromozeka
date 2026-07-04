# LLM `useTools` Per-Tool Filtering

Durable notes from the per-tool filtering implementation for `useTools` (2026-07-04). Read this when working on LLM tool registration, tool filtering, or the `ToolName` StrEnum.

- `LLMService.generateTextViaLLM` / `LLMMessageHandler._generateTextViaLLM` `useTools` param extended from `bool` to `bool | dict[str, bool]`.
- **`UseToolsType`** type alias: defined in `internal/services/llm/service.py`, re-exported from `internal/services/llm/__init__.py` (and imported into `llm_messages.py`).
- **`ToolName` StrEnum** lives in [`internal/bot/constants.py`](../../../internal/bot/constants.py) — one member per registered LLM tool (19 members, e.g. `RUN_PYTHON`, `WEB_SEARCH`, `SEARCH_MESSAGES`). Each member's value matches the `name=` passed to `registerTool`. This is the **first** StrEnum in that module (which previously held only scalar constants).
- **`TOOLS_DEFAULT_DICT_KEY = "default"`** module-level constant in `internal/bot/constants.py` — the reserved sentinel key in the `useTools` dict used by `_resolveTools` for fallback tool enablement.
- **Constructing dicts**: use `ToolName.XXX` members as keys (not raw strings) — they serialize correctly because `ToolName` is a `StrEnum`, but the enum form is type-safe and greppable. Use `TOOLS_DEFAULT_DICT_KEY` (not the literal `"default"`) for the fallback key. Raw strings also work but are discouraged.
- **Dict semantics**: `TOOLS_DEFAULT_DICT_KEY` ("default") key is the fallback for unspecified tools (defaults to `False` when absent). Unknown tool names → `logger.warning`, silently ignored.
- **Resolver**: private `_resolveTools(useTools) -> List[LLMToolFunction]` returns the filtered list sent to the model. All 19 `registerTool(name=...)` call sites across the handler tree now use `ToolName.XXX` instead of raw string literals.
- **Execution guard**: the tool-execution loop checks against `filteredToolNames` (the resolved subset), NOT the full `toolsHandlers` registry. A dict-disabled tool request now returns an error listing only the actually-available tools, so the LLM isn't tempted to retry a disabled tool. Error wording changed: "not found" → "not available", and the available list is now `sorted(filteredToolNames)` (was `list(registry.keys())`).
- **Tests**: `tests/services/llm/test_use_tools.py` (20 tests).
- **Note**: the default `useTools` in `LLMMessageHandler._sendLLMChatMessage` still flows from `ChatSettingsKey.USE_TOOLS.toBool()` — i.e. only `True`/`False`. Callers that want dict-level filtering must construct the dict explicitly (no chat setting drives the dict form yet).

## `internal/bot/constants.py`

- Historical home of scalar bot constants (emojis, Telegram limits, processing timeouts, weather/geocoder coefficients).
- Now also hosts the `ToolName` StrEnum (19 members, one per registered LLM tool) and the `TOOLS_DEFAULT_DICT_KEY = "default"` sentinel constant — both added to support type-safe per-tool filtering in the `useTools` dict.
- `ToolName` is the **first** StrEnum in this module; when adding a new LLM tool, add a member here AND a matching `registerTool(name=ToolName.YOUR_TOOL, ...)` call site.
