# Teamlead Memory

Durable working memory for `.opencode/agents/teamlead.md`.

How to use this file:
- Read it at the beginning of every task.
- If the task touches a subsystem with archived task memory under [`memories/`](memories/index.md), read the relevant file too.
- Re-read it when prior context feels uncertain or incomplete.
- Update it immediately after learning durable new information.
- Consolidate and clean it before finishing a task.
- Store reusable facts, not temporary task chatter.
- Never store secrets, tokens, `.env` values, or raw logs.

## User Preferences

- Uses `TASK_STATE.md` at repo root as a resumable task-state file for multi-session work.
- Prefers parallel batching for independent subtasks (e.g., 6 files at once).
- Docstring improvement passes should follow one-file-per-task pattern with gate reviews between batches.

## Task-Specific Memory Files

- [`memories/sandbox.md`](memories/sandbox.md) — archived durable notes from the completed `lib/sandbox` / sandbox-handler work. Read it only when touching sandbox code, config, or docs.

## Repo Facts And Gotchas

- `lib/utils/ttl_dict.py` provides a thread-safe TTL dict with GC, lazy expiration, and full dict API. Uses sentinel pattern for unspecified TTL vs ttl=None.
- `pathlib.relative_to()` is preferred over `str.startswith()` for path containment checks (cross-platform, handles symlinks/trailing slashes).
- `dict.setdefault()` is the canonical one-liner fix for check-then-create race conditions in CPython (GIL-protected).
- Async tests should use `async def test_...` without `@pytest.mark.asyncio`; `asyncio_mode = "auto"` handles them.
- Bot handler config-gating pattern: `if self.configManager.get("section", {}).get("enabled", False)` in HandlersManager, register before LLMMessageHandler (line ~534). Use `HandlerParallelism.PARALLEL` for most handlers.
- Chat setting access: `settings[key][0]` returns the value (tuple is `(value, updatedBy)`). Direct indexing preferred, not `.get()`. Writes need keyword-only `updatedBy=`.
- `isBotOwner()` is on `BaseBotHandler` (not `_bot`). Mock it as `handler.isBotOwner = Mock(...)` in tests, not `handler._bot.isBotOwner`.
- `ConfigManager.get()` does NOT support dotted-path traversal — it is plain `dict.get(key, default)`. Always use nested `.get()` calls.
- Multi-section truncation: update cumulative length after each section or all sections share the same remaining space (overflow risk).
- `newMessageHandler` does NOT gate commands. Commands are dispatched via `@commandHandlerV2` decorator and bypass the message handler chain. Per-command access checks must be in each command method (use a shared `_checkAccess()` helper).
- LLM tool registration: `self.llmService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._method)` in `__init__`. Gate with feature-enabled flag. Imports: `from lib.ai import LLMFunctionParameter, LLMParameterType`.
- LLM tool handler signature: `async def _method(self, extraData: Optional[Dict[str, Any]], param1, ..., **kwargs: Any) -> str`. Must return JSON `{"done": bool, ...}` — NEVER raise. Get chat context from `extraData["ensuredMessage"]`.

## Teamlead Workflow Lessons

- The teamlead prompt grants direct read/edit/write access only for this file; all substantive project work must still be delegated.
- For multi-file docstring passes: batch by complexity (init files + small → medium → large → manager), run Gate 1 per-batch, then Gate 2 whole-work.
- When code reviewers flag a Returns: format inconsistency, propagate the fix to ALL files in that batch (or the entire library) at once to avoid repeat reviews.
- Explicit type prefix format in Returns: sections (e.g., `int: Number of sessions`) is WRONG for this project — use plain descriptions.
- Docstring correctness matters: always verify that docstring descriptions match actual implementation (not what the method is "supposed" to do).
- When fixing many small, independent issues from review documents: first explore thoroughly to determine which are already fixed, then batch independent fixes into parallel `software-developer` tasks (group by file to avoid conflicts), then do a single Gate 2 whole-work review. Per-subtask Gate 1 reviews are excessive for single-line fixes.
- Always verify the exploration phase — several candidate fixes may already be present from prior sessions. Avoid re-fixing fixed issues.
- When the same fact appears in a focused doc and in handler/class docstrings, update both surfaces explicitly; one does not propagate to the other.
- When a `software-developer` subagent returns empty twice for the same task, it likely hit the ~60 step budget. Switch approach: either give the user exact instructions (before/after code) and let them apply it, or try the `general` agent. For truly tiny edits (<10 lines), the brief should be absolutely minimal.
- Subagents may auto-commit their work (commit messages like `Fix some issues`). When this happens, `git diff HEAD` will not show those changes. For whole-work reviews, use `git diff <base-commit>..HEAD` to capture everything.

## Repo Facts And Gotchas (continued)

- `lib/ai/providers/basic_openai_provider.py`: `BasicOpenAIModel` has two image-generation transports: (1) `_generateImage()` using `chat.completions.create` with `modalities=["image", "text"]`, (2) `_generateImageViaImagesApi()` using `client.images.generate()`. Models opt into the second via `image_generation_api = "openai-images"` in `extraConfig`.
- Hook methods available for subclasses: `_getModelId()` (text models), `_getImageModelId()` (image models), `_getExtraParams()`, `_getImageRequestOptions()` (whitelisted image API params), `_getClientParams()` (extra AsyncOpenAI constructor kwargs).
- `YcOpenaiModel` uses `gpt://...` URIs for text and `art://...` URIs for images — two different URI schemes from the same provider.
- `YcOpenaiProvider._folderId` is set **before** `super().__init__()` so `_getClientParams()` (called during `_initClient()`) can access it. This ordering is critical.
- `_getClientParams()` affects ALL requests through the OpenAI client (text, images, tools), not just the API it was added for.
- `image_generation_api = "openai-images"` dispatch in `BasicOpenAIModel._generateImage()` is **generic** — it works for any `BasicOpenAIModel` subclass, not just `YcOpenaiModel`. Old docs claimed it was YC-only; this was corrected in `docs/llm/configuration.md`.

## Teamlead Workflow Lessons (continued)

- For multi-phase implementation from a design doc: exploration first to verify assumptions (code has drift), then implement foundation phase, review it, then wire consumers + config, review again, then docs, then whole-work review. Parallelize config changes with implementation phases when possible.
- When subagents fail with `ProviderModelNotFoundError`, check the `model:` field in each agent's `.md` file and in `.opencode/opencode.json` — the `standard` model may not be provisioned while `cheap`/`smart`/`smartest` are.
- The `explore` subagent (model: `cheap`) and `code-reviewer` (model: `smart`) are reliable for read-only work; `software-developer` needs `standard` model to be functional.
- When production code has `isinstance(x, SomeType)` guards, mock objects in tests need `MagicMock().__class__ = SomeType` to pass them. Cleaner than constructing real SDK objects and doesn't require knowing all constructor params.
- If the user adds guards to production code and tests break, fix the tests — don't remove the guards. The user's intent is clear: guards are there by design.

## New Conventions (from proxy refactoring, 2026-05-23)

- **String enums: use `StrEnum` (from `enum`), NOT `Literal["a", "b"]`.** The project prefers `StrEnum` for named string constants. Example: `class ProxyType(StrEnum): HTTP = "http"`.
- **NEVER use imports inside functions/methods.** All imports go at the top of the file. For optional dependencies, use `try/except ImportError` at module level with a `_AVAILABLE` flag. Example:
  ```python
  try:
      from httpx_socks import AsyncProxyTransport
      _HTTPX_SOCKS_AVAILABLE = True
  except ImportError:
      _HTTPX_SOCKS_AVAILABLE = False
  ```
- **lib/proxy is a package** (`lib/proxy/__init__.py`), not a single file. Internal modules can be added under `lib/proxy/` in the future.
- **ProxyKwargs TypedDict** for proxy kwargs (instead of generic `Dict[str, Any]`): `class ProxyKwargs(TypedDict, total=False): proxy: str; transport: Any`.
- **Global proxy storage:** `setGlobalProxyConfig()` called once from `main.py`; `getGlobalProxyConfig()` used by all services. No threading through constructors.
- **Config key for per-service proxy overrides is `proxy`** (not `proxy-override`). Example: `[bot.proxy]`, `[yandex-search.proxy]`.
- **Responses must be in English** (user preference).
- **requirements.txt is frozen.** Add dependencies to ``requirements.direct.txt`` (``# Runtime`` section), never to ``requirements.txt`` directly.

## Anti-Patterns to Avoid (proxy refactoring lesson, 2026-05-23)

- **Free-function sprawl over class-based design.** When a feature needs state (global config) and multiple operations that compose together (resolve → merge → build URL → build kwargs), prefer a cohesive class with methods over a collection of module-level free functions. A class with `fromDict`/`fromServiceDict` classmethods, `getCombined`/`getProxyURL`/`toKwargs` instance methods is clearer, more discoverable, and easier to test than four separate functions that call each other.

- **Config threading through constructors when a singleton works better.** If every service and every layer of the call chain needs the same config value, use the project's established singleton pattern (`getInstance()` / `setGlobalConfig()`) instead of adding a new parameter to every constructor in the call chain. This keeps signatures clean and avoids parameter pollution.

- **Always use project patterns from the start.** Before implementing anything, check: are there StrEnum values I should define? Do I need a TypedDict for the return type? Should optional dependencies use the module-level try/except pattern? Applying these patterns upfront avoids a large refactoring later.

- **Avoid `Literal["a", "b"]` in favor of `StrEnum`.** `StrEnum` provides named constants, string serialization, IDE auto-completion, and safe refactoring. Literal types are type-system-only and provide none of these.

- **Never add `__dict__` to `__slots__` as a test-mocking workaround.** Adding
  ``"__dict__"`` to ``__slots__`` completely defeats the purpose (no memory
  savings, no attribute-access optimisation). Instead, fix the tests to mock at
  the class level (``patch.object(ClassName, "_method", ...)`` rather than
  ``patch.object(instance, "_method", ...)``). Class-level mocking works on
  slotted classes without ``__dict__``.

- **`requirements.txt` vs `requirements.direct.txt`.** ``requirements.txt`` is
  a frozen/locked file — never add non-pinned entries there. All direct
  dependencies go in ``requirements.direct.txt`` under the ``# Runtime``
  section with a version constraint. ``httpx-socks[asyncio]>=0.10.0`` should
  be in ``requirements.direct.txt``, not ``requirements.txt``.

- **No PEP 695 `type` aliases or dummy stubs for conditional-import fallbacks.** The
  ``type AsyncProxyTransport = NoneType`` pattern confuses pyright — it
  can't reconcile a ``TypeAliasType`` with a runtime class. Dummy stub classes
  are also unnecessary. Simply leave the ``except ImportError`` block empty
  aside from setting the ``_AVAILABLE`` flag to ``False``. Pyright follows the
  ``try`` branch for type resolution, and the ``_AVAILABLE`` guard prevents
  any runtime access to the undefined name.

## Proxy Support (completed 2026-05-23, refactored)

- **Status:** IMPLEMENTED. 2373 tests passing. All review gates passed.
- **Design:** `lib/proxy/__init__.py` — `ProxyConfig` class (uses `__slots__`), `ProxyKwargs` TypedDict; `ProxyType` StrEnum; `ProxyHelper` singleton. Resolution is done via `ProxyConfig.fromServiceDict()` (per-service) and `ProxyConfig.getCombined()` (merge with global). `ProxyConfig.getProxyURL(maskPassword=True)` for safe logging. `ProxyConfig.toKwargs()` for httpx kwargs.
- **Config hierarchy:** Global `[proxy]` section + per-service `use-proxy` (kebab-case) + optional `[service.proxy]` overrides. Master kill-switch `[proxy].enabled = false`.
- **Proxied services:** Telegram bot, Max client, all OpenAI-compatible AI providers, Yandex Search API, web-fetch, OpenWeatherMap, Geocode Maps, sqlink database provider.
- **Out of scope:** YC SDK (gRPC), sandbox (container networking).
- **SOCKS5:** `httpx-socks[asyncio]>=0.10.0` in requirements.txt. Conditional import at module level.
- **Key files:** `lib/proxy/__init__.py` (package), `lib/ai/abstract.py` (aclose), `lib/ai/providers/basic_openai_provider.py` (proxy + aclose), `internal/bot/telegram/application.py` (PTB proxy), `lib/max_bot/client.py`, `lib/openweathermap/client.py`, `lib/geocode_maps/client.py`, `lib/yandex_search/client.py`, `internal/bot/common/handlers/yandex_search.py`, `internal/bot/common/handlers/weather.py`, `internal/database/providers/sqlink.py`, `internal/database/providers/__init__.py` (sqlink proxy resolution), `main.py` (`ProxyHelper.getInstance().setGlobalProxyConfig()`).
- **Tests:** `tests/lib/test_proxy.py` — 41 tests.
- **Security:** `ProxyConfig.getProxyURL(maskPassword=True)` for logging (password → `REDACTED`). URL building uses `quote()` for credential encoding.

### Complete HTTP Client Inventory (from 2026-05-23 audit)

**In scope (all need proxy):**

| # | Service | File | Library | Persistence |
|---|---------|------|---------|-------------|
| 1 | Max Messenger client | `lib/max_bot/client.py:188` | `httpx.AsyncClient` | Persistent (`self._httpClient`) |
| 2 | Telegram bot | `internal/bot/telegram/application.py:365` | `python-telegram-bot` (httpx internally) | Persistent (PTB-managed) |
| 3 | OpenAI-compatible providers | `lib/ai/providers/basic_openai_provider.py:969` | `openai.AsyncOpenAI` | Persistent (`self._client`) |
| 4 | Image download (OpenAI) | `lib/ai/providers/basic_openai_provider.py:826` | `httpx.AsyncClient` | Ephemeral |
| 5 | OpenRouter listRemoteModels | `lib/ai/providers/openrouter_provider.py:290` | `httpx.AsyncClient` | Ephemeral |
| 6 | Yandex Search API | `lib/yandex_search/client.py:354` | `httpx.AsyncClient` | Ephemeral |
| 7 | Web-fetch (yandex_search handler) | `internal/bot/common/handlers/yandex_search.py:469` | `httpx.AsyncClient` | Ephemeral |
| 8 | OpenWeatherMap | `lib/openweathermap/client.py:453` | `httpx.AsyncClient` | Ephemeral |
| 9 | Geocode Maps | `lib/geocode_maps/client.py:479` | `httpx.AsyncClient` | Ephemeral |

**Out of scope:**
- YC SDK provider (`yandex_ai_studio_sdk` — gRPC)
- Sandbox Docker backend (`aiodocker` — container networking)
- S3 storage backend (`boto3` — separate proxy story)
- Aurumentation test infra (not production)
- `requests` library — not used in production code

## Test Reorganization (completed 2026-05-21)

- Plan document: [`docs/plans/test-reorganization.md`](../../docs/plans/test-reorganization.md) — full mapping tables, phases, risks.
- **Completed:** All ~74 test files moved from collocated locations into `tests/` with source-structure mirroring.
- **Conventions:**
  - `internal/X/Y.py` → `tests/X/test_Y.py` (strip `internal/` prefix).
  - `lib/X/Y.py` → `tests/lib/X/test_Y.py` (full `tests/lib/` prefix).
  - Cross-cutting tests stay at `tests/integration/`, `tests/verification/`.
  - `testpaths` stays `["tests", "lib", "internal"]` (lib/ and internal/ now have no test files; harmless).
- Old directories `tests/lib_ai/`, `tests/lib_utils/`, `tests/lib_ratelimiter/`, `tests/divination/`, `tests/geocode_maps/`, `tests/openweathermap/`, `tests/yandex_search/` removed.
- Non-test files (`lib/markdown/test/run_tests.sh`, `README.md`, `MarkdownV2_demo.py`) remain in place under `lib/markdown/test/`.
  - Final: **2342 passed, 11 skipped** (skipped = Docker sandbox tests without daemon).
- **New test rule** (added to `docs/llm/testing.md`, `AGENTS.md`, `docs/llm/index.md`, `docs/llm/tasks.md`): all new tests MUST use mirror layout under `tests/`. No new collocated tests in `lib/` or `internal/`.
- **Post-reorg doc audit**: `docs/llm/` and `AGENTS.md` are clean. Fixed stale paths in `docs/plans/` (10 files), `docs/design/` (1 file), `docs/templates/` (1 file), `docs/suggestions/` (1 file), `.agents/skills/` (1 file), `internal/database/migrations/README.md`. Left `docs/archive/` untouched (historical records).
