# Any Type Cleanup

Durable notes from the repo-wide `Any` type annotation audit and cleanup (2026-06-28). Read this when working on type annotations, encountering `Any` usage, or setting up type narrowing patterns.

## Summary

Full audit and fix of `Any` type annotations in production code. 61 usages found across 24 files → 25 narrowed, 36 kept (genuine), 16 files changed.

## Files changed and what was done:

| File | Changes |
|---|---|
| `lib/ai/models.py` | `_OmitSentinel` class (real union for `str | _OmitSentinel`), `_StrOrOmit`/`_RendererCallable` aliases, `_renderStatus`→`str`, `LLMToolCall.id`→`str`, `toolCallId`→`Optional[str]`, `parameters`→`Dict[str, Any]` |
| `lib/ai/providers/basic_openai_provider.py` | `id=tool.id`→`id=tool.id or str(uuid.uuid4())` (null guard for `Optional[str]` from SDK) |
| `lib/ai/providers/fastembed_provider.py` | `embedOne` return: `Any`→`"np.ndarray"` (string forward ref) |
| `internal/database/database.py` | `__aexit__`: `Any`→`Optional[type[BaseException]]`, `Optional[BaseException]`, `Optional[types.TracebackType]` |
| `internal/database/providers/base.py` | Same `__aexit__` fix + logging bug fix (`exc_info=`) |
| `lib/max_bot/client.py` | `exc_tb: Optional[Any]`→`Optional[types.TracebackType]` |
| `internal/bot/common/handlers/spam.py` | `extra: Any = None`→`extra: bool = False` |
| `internal/services/llm/models.py` | `ExtraDataDict` fields: `TYPE_CHECKING`+forward refs (`"EnsuredMessage"`, `"Optional[TypingManager]"`) |
| `internal/services/llm/service.py` | `LLMToolHandler`→`Awaitable[Union[str, Dict[str, Any], None]]`, `parameters`→`Dict[str, Any]` |
| `internal/bot/models/command_handlers.py` | `CommandHandlerFunc*`: `TypeVar("_HandlerSelfT", bound="BaseBotHandler")`+`Optional["TypingManager"]` |
| `internal/config/manager.py` | `substituteEnvVars`: `TypeVar`+`cast(T, ...)` for honest `T→T` |
| `lib/aurumentation/collector.py` | `substituteEnvVars`: kept `Any→Any` (module/class branch makes `T→T` dishonest) + docstring note |
| `internal/bot/common/handlers/weather.py` | `_fixCountry`: `TypeVar`+`cast` for identity-like transform |
| `lib/markdown/parser.py` | `_OptionValue = Union[bool, int, str, Dict[str, Any]]` for `set_option`/`get_option` |
| `lib/aurumentation/types.py` | `cache: Optional[Any]`→`Optional[CacheInterface[str, Any]]` |

## Patterns established for future use:
- **`_OmitSentinel` class** with `__slots__`, `__repr__`, `__bool__` — enables real discriminated union `str | SentinelType`
- **`TYPE_CHECKING` + string forward refs** — textbook solution for circular-import workarounds (used in `ExtraDataDict`, `CommandHandlerFunc*`)
- **`TypeVar` + `cast(T, ...)`** — for identity-like recursive transforms (only when the contract is honest)
- **`assert` for Optional narrowing** — `assert x is not None` after `if guard` for pyright-compatible narrowing (accepted pattern)

## GENUINE patterns preserved:
- `**kwargs: Any` passthrough (12+ LLM tool handlers, markdown convenience functions, httpx params)
- `rawResult: Any` for provider-agnostic LLM responses
- `jsonDumps(data: Any)` — `default=str` fallback makes it genuinely any
- `convertToSQLite(data: Any)` — dispatches on type with `str()` fallback
- `ConfigManager.get(key, default=Any) -> Any` — generic config access
- `Dict[str, Any]` — JSON-like dicts (~20 files, excluded from audit scope)
