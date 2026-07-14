---
name: add-llm-tool
description: >
  Recipe for adding a new LLM tool to Gromozeka — a callable function the model
  can invoke during text generation (e.g. `run_python`, `search_messages`,
  `add_memory`). Covers all four coordinated sites that must change together:
  the `ToolName` StrEnum member, the `registerTool(...)` call in the handler's
  `__init__` (gated on a feature flag), the `_llmTool*` handler method (dict
  return, never-raise contract, `extraData` context), and chat-time gating in
  `_sendLLMChatMessage` for destructive/refinement-only tools. Encodes two
  load-bearing contracts that were recurring real bug classes: the
  never-raise contract (an unhandled exception aborts the whole LLM
  generation) and the D3-gating rule (globally-registered destructive tools
  must be explicitly disabled at chat time). Triggers: add LLM tool, new LLM
  tool, register tool, ToolName, _llmTool, registerTool, LLM function
  calling, tool handler, chat-time tool gating, useTools.
---

# Add an LLM Tool

An **LLM tool** is a function the language model can call mid-generation
(weather lookup, sandboxed code run, memory search, etc.). It is registered on
the `LLMService` singleton and surfaced to the model via the tool-calling
protocol. This skill covers adding one end-to-end.

## When to use

- Adding a brand-new callable the LLM may invoke during `generateTextViaLLM` (a
  new capability the model can decide to use: search, compute, fetch, store).
- Promoting an existing internal helper into an LLM-callable tool.

## When NOT to use

- The capability is a **slash command** (`/foo`) for the user, not something the
  model calls autonomously → use [`add-handler`](../add-handler/SKILL.md) instead
  (a tool is a different surface from a `/command`, though one handler class can
  own both).
- You're only **changing an existing tool's description or parameters** → edit
  the `registerTool(...)` call site in place; no new `ToolName` member, no new
  method, no gating change.
- The model needs **structured output** (a JSON object returned directly to the
  caller, not a tool it calls) → that's `LLMService.generateStructured` /
  `ModelStructuredResult`, not a tool.
- You're adding a tool to a handler that already exists and already registers
  tools → just add the three pieces (enum member, `registerTool` call, `_llmTool*`
  method) to that handler; don't create a new handler class.

## Why this skill exists

The knowledge for "add an LLM tool" is scattered across five doc surfaces
([`docs/llm/index.md`](../../../docs/llm/index.md) §5,
[`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §1.5,
[`docs/llm/services.md`](../../../docs/llm/services.md),
[`add-handler`](../add-handler/SKILL.md) Step 5, and
[`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md)), and two
of the contracts were recurring real bug classes:

1. **Never-raise** — the tool-execution loop does **not** catch exceptions from
   handler methods. An unhandled raise aborts the entire LLM generation.
2. **D3 gating** (D3 — destructive-tool-disable rule) — tool registration is
   **global** on the `LLMService`
   singleton. `useTools=True` (bool) exposes **every** registered tool. A
   destructive/refinement-only tool that isn't explicitly excluded at chat time
   silently becomes chat-time-callable.

There are **four** coordinated sites. All four must change together for a
destructive tool; a safe read-only tool needs only the first three.

## Prerequisites

Load `read-project-docs` first; specifically:

- [`docs/llm/index.md`](../../../docs/llm/index.md) §5 — LLM Tool Registration.
- [`docs/llm/services.md`](../../../docs/llm/services.md) — `registerTool`
  signature and the `useTools` per-tool filtering contract.
- [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §1.5 — the decision tree.
- [`AGENTS.md`](../../../AGENTS.md) — naming rules, no-`Any` rule, regression-test rule.

## Site 1 — Add the `ToolName` StrEnum member

File: [`internal/bot/constants.py`](../../../internal/bot/constants.py), class
`ToolName`.

`ToolName` is a `StrEnum` whose string values are **snake_case** (NOT
kebab-case — that's `ChatSettingsKey`'s convention, a different enum):

```python
class ToolName(StrEnum):
    # ... existing members, grouped by feature ...
    YOUR_TOOL = "your_tool"
```

> **Convention:** `UPPER_CASE` Python name ↔ `snake_case` string value. The value
> is the exact string the model sees and emits in tool-call requests; it must
> match the `name=` passed to `registerTool`. Group the new member with its
> siblings (weather tools together, sandbox tools together, etc.) — the enum is
> organized by feature area.

### Real members for reference

Weather (`GET_WEATHER_BY_CITY`, `GET_WEATHER_BY_ADDRESS`, `GET_WEATHER_BY_COORDS`),
media (`GENERATE_AND_SEND_IMAGE`), Yandex (`WEB_SEARCH`, `GET_URL_CONTENT`),
chat search (`SEARCH_MESSAGES`, `LIST_USERS`, `GET_THREAD`), sandbox
(`RUN_PYTHON`, `SANDBOX_LIST_FILES`, `SANDBOX_READ_FILE`, `SANDBOX_SEND_FILE`,
`SANDBOX_LIST_LIBRARIES`), memories (`ADD_MEMORY`, `DELETE_MEMORY`,
`SEARCH_MEMORIES`), common (`GET_CURRENT_DATETIME`), example (`EXAMPLE`),
divination (`DO_TAROT_READING`, `DO_RUNES_READING`). Illustrative, not
exhaustive — see the enum for the live set.

## Site 2 — Register the tool in the handler's `__init__`

### 2a — Imports (top of file)

```python
from internal.bot.constants import ToolName
from lib.ai import LLMFunctionParameter, LLMParameterType
```

`LLMFunctionParameter` and `LLMParameterType` are re-exported from
[`lib/ai/__init__.py`](../../../lib/ai/__init__.py) (defined in
[`lib/ai/models.py`](../../../lib/ai/models.py)).

`LLMFunctionParameter` fields:

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Parameter name the model sees. |
| `description` | `str` | Human-readable; the model uses this to decide when to pass it. |
| `type` | `LLMParameterType` | One of `STRING`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT`. |
| `required` | `bool` | Default `False`. |

### 2b — The `registerTool` call, gated on a feature flag

The `registerTool` signature
([`internal/services/llm/service.py`](../../../internal/services/llm/service.py)
~line 217 — line numbers drift over time; grep `def registerTool` for the stable
anchor):

```python
def registerTool(
    self, name: str, description: str, parameters: Sequence[LLMFunctionParameter], handler: LLMToolHandler
) -> None: ...
```

In the handler's `__init__`, after `super().__init__(...)`:

```python
if self.configManager.get("my_feature", {}).get("enabled", False):
    self.llmService.registerTool(
        name=ToolName.YOUR_TOOL,
        description="What your tool does, written for the model to read.",
        parameters=[
            LLMFunctionParameter(
                name="param",
                description="What this parameter means.",
                type=LLMParameterType.STRING,
                required=True,
            ),
        ],
        handler=self._llmToolYourTool,
    )
```

Key rules:

- ❌ **Never** pass a raw string for `name=` — use `ToolName.YOUR_TOOL`. Raw
  strings technically work (it's a `StrEnum`) but defeat the type-safety and
  greppability the enum exists for.
- ✅ **Gate registration** on the feature's `enabled` flag. An un-gated tool is
  registered unconditionally on a singleton — it would be globally available
  even when the feature is meant to be off. If the flag is brand-new, add it to
  [`configs/00-defaults/bot-defaults.toml`](../../../configs/00-defaults/bot-defaults.toml)
  first (see [`add-handler`](../add-handler/SKILL.md)) — otherwise
  `configManager.get(..., {}).get('enabled', False)` silently stays `False`.
- The `description` is read by the model. Be concrete about *when* to call the
  tool and *what* each parameter does — see the existing sites (e.g.
  [`user_memories.py`](../../../internal/bot/common/handlers/user_memories.py)
  ~line 260) for the expected density.

> **The handler-vs-gating distinction:** gating registration (this site) controls
> whether the tool is registered **at all**. Chat-time gating (Site 4) controls
> whether a *registered* tool is offered during a normal chat turn. They
> compose — a handler that is never constructed registers nothing; a handler
> that is constructed but whose tool must stay refinement-only needs both.

For concrete examples of the full registration block, see
[`example.py`](../../../internal/bot/common/handlers/example.py) (minimal),
[`sandbox.py`](../../../internal/bot/common/handlers/sandbox.py) ~line 99
(multi-parameter), or [`user_memories.py`](../../../internal/bot/common/handlers/user_memories.py)
~line 260 (feature-gated, multiple tools).

## Site 3 — Implement the `_llmTool*` handler method

### Signature

```python
async def _llmToolYourTool(
    self,
    extraData: Optional[Dict[str, object]],
    param: str,
    *,
    optionalParam: Optional[str] = None,
    **kwargs: object,
) -> Dict[str, object]:
```

- First parameter is always `extraData: Optional[Dict[str, object]]` — the context
  dict the LLM service passes through. It carries `ensuredMessage` (the chat
  context), and may carry feature flags like `isRefinement`.
- Declared tool parameters come next, by name. They arrive as keyword arguments
  from the model's JSON tool-call arguments.
- `**kwargs: object` catches anything the model passes that you didn't declare —
  always include it so an unexpected argument doesn't crash the dispatcher.
- Return type is `Dict[str, object]`. Use `object` (not `Any`) for arbitrary
  passthrough — this matches the repo's no-`Any` rule and the newest handlers
  ([`user_memories.py`](../../../internal/bot/common/handlers/user_memories.py)
  `_llmToolAddMemory`, `_llmToolSearchMemories`).

### The never-raise contract

> ⚠️ **CRITICAL — the tool-execution loop does NOT catch exceptions from your
> handler.** An unhandled raise aborts the **entire** LLM generation — the user
> sees an error instead of a reply. Wrap the whole body in `try/except` and fold
> every failure into the return dict:

```python
async def _llmToolYourTool(
    self, extraData: Optional[Dict[str, object]], param: str, **kwargs: object
) -> Dict[str, object]:
    """<One-line summary of what the tool does.>

    Args:
        extraData: Context dict; must carry ``ensuredMessage``.
        param: <What param means.>
        **kwargs: Ignored (model may send extra args).

    Returns:
        ``{"done": True, ...}`` on success, ``{"done": False, "error": ...}``
        on any failure. Never raises.
    """
    try:
        ensuredMessage = extraData.get("ensuredMessage") if extraData else None
        if not isinstance(ensuredMessage, EnsuredMessage):
            return {"done": False, "error": "Missing ensuredMessage"}

        # ...do the work, using ensuredMessage.recipient.id / .sender.id /
        #    .threadId for chat context...

        return {"done": True, "result": "..."}
    except Exception as e:
        logger.exception("_llmToolYourTool: failed")
        return {"done": False, "error": str(e)}
```

Rules:

- ✅ **Return a dict**, e.g. `{"done": True, "result": ...}` or
  `{"done": False, "error": "..."}`. The LLM service serializes it to JSON for
  the model.
- ℹ️ **Dict is the modern convention; don't introduce new string returns.**
  The `LLMToolHandler` type alias
  ([`service.py`](../../../internal/services/llm/service.py) ~line 38) permits
  `str | Dict[str, Any] | None`, and `None` is serialized as `'null'`, so string
  and `None` returns technically work — but they're the older style. Live
  string-returners exist (`_llmToolGetCurrentDateTime` in
  [`common.py`](../../../internal/bot/common/handlers/common.py) ~line 165 and
  `_llmToolExample` in [`example.py`](../../../internal/bot/common/handlers/example.py)
  both return `json.dumps(...)`); they predate the dict convention and should not
  be copied. New tools should return a dict.
- ✅ **Get chat context from `extraData["ensuredMessage"]`** — `chatId` =
  `ensuredMessage.recipient.id`, `userId` = `ensuredMessage.sender.id`,
  `threadId` = `ensuredMessage.threadId or DEFAULT_THREAD_ID` (`DEFAULT_THREAD_ID`
  is `0`, not `None`). Guard with an `isinstance(ensuredMessage, EnsuredMessage)`
  check and return `{"done": False, "error": "Missing ensuredMessage"}` if absent.
- ✅ **Validate model-supplied input defensively** — the model can pass `None`,
  wrong types, or out-of-range values. Clamp numeric `limit` params to `[1, MAX]`,
  validate enum-string params against the real enum, return a helpful error dict
  on bad input (see [`user_memories.py`](../../../internal/bot/common/handlers/user_memories.py)
  `_llmToolSearchMemories` ~line 647 for the clamp pattern).
- ✅ **Wrap any `rateLimit` / cross-module awaitable in try/except** —
  `LLMService.rateLimit()` can raise `RuntimeError`/`ValueError`; see the note in
  [`docs/llm/memories/chat-history-search.md`](../../../docs/llm/memories/chat-history-search.md).

## Site 4 — Chat-time gating (destructive / refinement-only tools only)

> ⚠️ **D3 gating gotcha — registration is GLOBAL.** `LLMService` is a singleton.
> `registerTool(...)` adds the tool to the single shared registry. When
> `_sendLLMChatMessage` passes `useTools=True` (the bool form), `_resolveTools`
> returns **every** registered tool. There is no per-handler, per-chat scoping at
> registration time. The only way to hide a registered tool from the chat-time
> turn is to list it as `False` in the `useTools` dict constructed in
> `_sendLLMChatMessage`.

**You need this site if and only if** the tool must NOT be freely callable from
a casual chat turn. Two cases:

1. **Always-off at chat time** (destructive / refinement-only) — e.g.
   `DELETE_MEMORY` deletes user data; it must only ever run from the refinement
   pass, never because the model fancied it mid-conversation.
2. **Conditionally-off** behind a chat setting — e.g. the sandbox tools are
   disabled when `ALLOW_SANDBOX=false`; the memory tools when `MEMORY_ENABLED=false`.
   If the gating chat setting doesn't exist yet, load
   [`add-chat-setting`](../add-chat-setting/SKILL.md) first — that's a whole
   second four-site workflow (enum member, `_chatSettingsInfo`, TOML default,
   consumers) that must complete before this gate can read it.

A **safe read-only tool** (weather, datetime, search) does **not** need this site
— the `TOOLS_DEFAULT_DICT_KEY: True` wildcard exposes it automatically.

### Where to edit

File:
[`internal/bot/common/handlers/llm_messages.py`](../../../internal/bot/common/handlers/llm_messages.py),
method `_sendLLMChatMessage` (line 220); the `useTools` block is at ~line 274.
When `USE_TOOLS` is on, the method builds the dict form:

```python
useTools = chatSettings[ChatSettingsKey.USE_TOOLS].toBool()
if useTools:
    useTools = {
        constants.TOOLS_DEFAULT_DICT_KEY: True,
        constants.ToolName.DELETE_MEMORY: False,  # always-off at chat time (D3)
    }
    if not chatSettings[ChatSettingsKey.ALLOW_SANDBOX].toBool():
        useTools.update({  # conditional-off
            constants.ToolName.RUN_PYTHON: False,
            # ...other sandbox tools...
        })
    if not chatSettings[ChatSettingsKey.MEMORY_ENABLED].toBool():
        useTools.update({  # conditional-off
            constants.ToolName.ADD_MEMORY: False,
            constants.ToolName.SEARCH_MEMORIES: False,
        })
```

To add your tool:

- **Always-off:** add `constants.ToolName.YOUR_TOOL: False,` to the base dict
  (alongside `DELETE_MEMORY`).
- **Conditional-off:** add a guarded `useTools.update({constants.ToolName.YOUR_TOOL: False})`
  behind the relevant chat setting check.

❌ **Do not** widen the `if useTools:` guard. An earlier bug guarded the whole
block with `if useTools and not all([useSandbox]):`, so when `ALLOW_SANDBOX=true`
the block was skipped entirely, `useTools` stayed the plain bool `True`, and
`_resolveTools` returned **all** registered tools including `DELETE_MEMORY`. The
override must always run when `useTools` is truthy. This regression is pinned by
`TestD3DeleteMemoryGating` (see Tests below).

> **Memory-refinement tools: a 5th coordinated enablement site.** The memory
> refinement pass builds its **own** `useTools` dict in
> [`user_memories.py`](../../../internal/bot/common/handlers/user_memories.py)
> `_runMemoryRefinement` (~line 1306), and it explicitly sets
> `ToolName.DELETE_MEMORY: True` (plus `ADD_MEMORY`, `SEARCH_MEMORIES`, etc.) —
> bypassing the chat-time gate above by design, so the refinement LLM can mutate
> memories. A **new** memory tool that you gate `False` at chat time must ALSO be
> added `True` here, or the refinement LLM won't be able to call it.

## Step 5 — Tests

Three things to cover. Test files live under
[`tests/bot/common/handlers/`](../../../tests/bot/common/handlers/) (the test
tree mirrors production: `internal/bot/common/handlers/foo.py` →
`tests/bot/common/handlers/test_foo.py`).

### 5a — Registration is gated by the flag

When the feature flag is **off**, the handler's `__init__` must **not** call
`registerTool` for your tool. When **on**, it must. The shared `mockBot` fixture
in [`tests/conftest.py`](../../../tests/conftest.py) stubs `llmService` with a
`Mock`; for registration assertions, construct the handler against a real or
partially-real `LLMService` and inspect `handler.llmService.toolsHandlers`, or
assert on the `registerTool` mock's call args.

### 5b — The handler method returns a dict and never raises

- Call `_llmToolYourTool` with valid input → assert it returns a dict with
  `"done": True` and the expected payload.
- Call with **bad input** (missing `ensuredMessage`, `None` param, out-of-range
  `limit`, invalid enum value) → assert it returns `{"done": False, "error": ...}`
  and does **not** raise. This is the regression for the never-raise contract.
- Build a real `EnsuredMessage` for `extraData["ensuredMessage"]` (never a raw
  dict) — import from `internal.bot.models`.

### 5c — Chat-time gating (if your tool needs Site 4)

If your tool must be excluded at chat time, add a parametrized test in
[`tests/bot/common/handlers/test_llm_messages.py`](../../../tests/bot/common/handlers/test_llm_messages.py)
modelled on `TestD3DeleteMemoryGating`: register your tool on the handler's
`LLMService`, drive `_sendLLMChatMessage`, capture the `useTools` passed to
`generateTextViaLLM`, resolve via `_resolveTools`, and assert your tool name is
**not** in the resolved set — across the relevant setting combos. For
conditional-off tools, also assert the tool **is** present when its enabling
setting is on (so you don't over-disable).

## Step 6 — Documentation

Load [`update-project-docs`](../update-project-docs/SKILL.md) for the full matrix.
The surfaces to touch:

- [`docs/llm/handlers.md`](../../../docs/llm/handlers.md) — the handler's row in
  the handler table: list the new tool (`ToolName.XXX`), its parameters, and the
  gating predicate.
- [`docs/llm/services.md`](../../../docs/llm/services.md) — the tool list /
  `useTools` examples, if your tool illustrates a new gating pattern.
- [`docs/llm/configuration.md`](../../../docs/llm/configuration.md) — if you
  added a config section or chat setting that gates the tool.
- [`docs/llm/index.md`](../../../docs/llm/index.md) §5 — only if the summary
  there is now misleading.

## Step 7 — Quality gates

Load [`run-quality-gates`](../run-quality-gates/SKILL.md). Short form:

```bash
make format lint
make test
```

> **Per [`AGENTS.md`](../../../AGENTS.md):** a regression test is mandatory on
> every fix. If you're adding this tool to fix a gap (e.g. "the model couldn't X"),
> the never-raise and gating tests in Step 5 are your regression coverage.

## Checklist

- [ ] `ToolName.YOUR_TOOL = "your_tool"` added to `internal/bot/constants.py`
      (`UPPER_CASE` name ↔ `snake_case` value), grouped with its feature siblings.
- [ ] Imports at top of handler file: `from internal.bot.constants import ToolName`
      and `from lib.ai import LLMFunctionParameter, LLMParameterType`.
- [ ] `registerTool(name=ToolName.YOUR_TOOL, description=..., parameters=[LLMFunctionParameter(...)], handler=self._llmToolYourTool)`
      in the handler's `__init__`, **gated on the feature's `enabled` flag**.
- [ ] No raw string literal for `name=` — `ToolName.YOUR_TOOL` everywhere.
- [ ] `_llmToolYourTool` method: `async def _llmToolYourTool(self, extraData: Optional[Dict[str, object]], ..., **kwargs: object) -> Dict[str, object]`
      (`object`, not `Any`, for arbitrary passthrough — repo no-`Any` rule).
- [ ] Method body wrapped in `try/except` — **never raises**; failures return
      `{"done": False, "error": ...}`.
- [ ] Returns a **dict** (`{"done": True, ...}`); string / `None` returns are the
      older style — don't introduce new ones.
- [ ] If the feature flag is new: added to `configs/00-defaults/bot-defaults.toml`.
- [ ] Chat context resolved from `extraData["ensuredMessage"]` with an
      `isinstance` guard; `threadId` via `ensuredMessage.threadId or DEFAULT_THREAD_ID`.
- [ ] Model-supplied input validated/clamped defensively.
- [ ] If the tool is destructive or refinement-only: explicitly set to `False`
      in the `useTools` dict in `_sendLLMChatMessage` (Site 4); did **not** widen
      the `if useTools:` guard. If it's a **memory-refinement** tool, also added
      `True` in `_runMemoryRefinement`'s `useTools` (user_memories.py ~line 1306).
- [ ] If Site 4 case 2 needs a brand-new chat setting: ran
      [`add-chat-setting`](../add-chat-setting/SKILL.md) first.
- [ ] Tests: registration gated by flag; handler returns dict and never raises
      on bad input; (if Site 4 applies) gating test in `test_llm_messages.py`
      modelled on `TestD3DeleteMemoryGating`.
- [ ] `docs/llm/handlers.md` (and services.md / configuration.md as needed) updated.
- [ ] `make format lint && make test` green.
