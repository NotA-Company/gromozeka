---
category: reference
---

# LLM `useTools` Per-Tool Filtering

Durable notes from the per-tool filtering implementation for `useTools` (2026-07-04). Read this when working on LLM tool registration, tool filtering, or the `ToolName` StrEnum.

- `LLMService.generateTextViaLLM` / `LLMMessageHandler._generateTextViaLLM` `useTools` param extended from `bool` to `bool | dict[str, bool]`.
- **`UseToolsType`** type alias: defined in `internal/services/llm/service.py`, re-exported from `internal/services/llm/__init__.py` (and imported into `llm_messages.py`).
- **`ToolName` StrEnum** lives in [`internal/bot/constants.py`](../../../internal/bot/constants.py) — one member per registered LLM tool (22 members as of this writing, e.g. `RUN_PYTHON`, `WEB_SEARCH`, `SEARCH_MESSAGES`, `EXAMPLE`, `DO_TAROT_READING`, `DO_RUNES_READING`). Each member's value matches the `name=` passed to `registerTool`. This is the **first** StrEnum in that module (which previously held only scalar constants). Re-count before relying on the number — new tools add members here.
- **`TOOLS_DEFAULT_DICT_KEY = "default"`** module-level constant in [`internal/services/llm/constants.py`](../../../internal/services/llm/constants.py) (re-exported from [`internal.services.llm`](../../../internal/services/llm/__init__.py)) — the reserved sentinel key in the `useTools` dict used by `_resolveTools` for fallback tool enablement. It is a shared contract: handlers that *build* the `useTools` dict and `LLMService._resolveTools` that *reads* it both import it from the service layer.
- **Constructing dicts**: use `ToolName.XXX` members as keys (not raw strings) — they serialize correctly because `ToolName` is a `StrEnum`, but the enum form is type-safe and greppable. Use `TOOLS_DEFAULT_DICT_KEY` (not the literal `"default"`) for the fallback key. Raw strings also work but are discouraged.
- **Dict semantics**: `TOOLS_DEFAULT_DICT_KEY` ("default") key is the fallback for unspecified tools (defaults to `False` when absent). Unknown tool names → `logger.warning`, silently ignored.
- **Resolver**: private `_resolveTools(useTools) -> List[LLMToolFunction]` returns the filtered list sent to the model. All `registerTool(name=...)` call sites across the handler tree (22 at present — one per `ToolName` member) use `ToolName.XXX` instead of raw string literals.
- **Execution guard**: the tool-execution loop checks against `filteredToolNames` (the resolved subset), NOT the full `toolsHandlers` registry. A dict-disabled tool request now returns an error listing only the actually-available tools, so the LLM isn't tempted to retry a disabled tool. Error wording changed: "not found" → "not available", and the available list is now `sorted(filteredToolNames)` (was `list(registry.keys())`). **Post-budget (`roundN >= maxRounds`):** `filteredToolNames` is cleared to `set()`, tool-call healing is disabled, AND the TOOL_CALLS execution branch is skipped entirely (gated on `not budgetExhausted`), so NO tool can execute past the cap and the loop terminates within one extra round regardless of provider behaviour.
- **Tests**: `tests/services/llm/test_use_tools.py` (21 tests).
- **Note (chat-time gating in `_sendLLMChatMessage`)**: the seed value still comes from `ChatSettingsKey.USE_TOOLS.toBool()`, but when that is `True` the handler expands it into a per-tool dict before calling `_generateTextViaLLM` — so the dict form **is** reached on the main chat path, driven by other chat settings (the D3-gating rule from the `add-llm-tool` skill: globally-registered destructive tools must be explicitly disabled at chat time). The current expansion:
  - `TOOLS_DEFAULT_DICT_KEY: True` (everything not explicitly listed is enabled) **and** `ToolName.DELETE_MEMORY: False` (refinement-only, never offered to the model in chat).
  - When `ChatSettingsKey.ALLOW_SANDBOX` is false: `RUN_PYTHON`, `SANDBOX_LIST_FILES`, `SANDBOX_LIST_LIBRARIES`, `SANDBOX_READ_FILE`, `SANDBOX_SEND_FILE` all forced off.
  - When `ChatSettingsKey.MEMORY_ENABLED` is false: `ADD_MEMORY`, `SEARCH_MEMORIES` forced off.
  When `USE_TOOLS` is false the bool propagates through unchanged (all tools disabled). Callers other than `_sendLLMChatMessage` that want dict-level filtering still construct the dict explicitly.

## `internal/bot/constants.py`

- Historical home of scalar bot constants (emojis, Telegram limits, processing timeouts, weather/geocoder coefficients).
- Hosts the `ToolName` StrEnum (22 members at present, one per registered LLM tool) — added to support type-safe per-tool filtering in the `useTools` dict. (The `TOOLS_DEFAULT_DICT_KEY` sentinel used to live here too; it was relocated to `internal/services/llm/constants.py` as part of the LLM-service layering cleanup — see [`services.md`](../services.md).)
- `ToolName` is the **first** StrEnum in this module; when adding a new LLM tool, add a member here AND a matching `registerTool(name=ToolName.YOUR_TOOL, ...)` call site.
