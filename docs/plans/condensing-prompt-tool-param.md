# `condensing_prompt` — per-call condensing instructions for `web_search` / `get_url_content`

- **Status:** Draft
- **Date:** 2026-07-17
- **Author:** teamlead / architect
- **Type:** Design + documentation (no code changes in this document)
- **Scope:** `internal/bot/common/handlers/yandex_search.py` (and tests)

---

## 1. Context / Problem

When `get_url_content` (or `web_search` with `return_page_content=true`) fetches a
page larger than `max_size`, the handler condenses it with an LLM before returning.
The condensing **system prompt** is read from the per-chat setting
`ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT`
(`internal/bot/models/chat_settings.py:340`), whose default is a generic
"detailed retelling preserving all ideas, arguments, facts and structure"
(`configs/00-defaults/bot-defaults.toml:250-254`).

That default is good for a generic summary, but the calling model often knows
what it actually needs from the page, e.g.:

- "extract only the recipe and ingredients list",
- "summarize just the financial figures and KPIs",
- "pull out the API endpoint signatures and parameter types",
- "translate the conclusion to English".

There is currently **no way for the model to tailor the condensing instructions per
call**. This design adds an optional `condensing_prompt` parameter to both LLM
tools, falling back to the existing per-chat default when not supplied, and fixes a
pre-existing `max_size` forwarding gap in `web_search`.

---

## 2. Current State (verified against source)

### 2.1 Tool registration

Both tools are registered in `YandexSearchHandler.__init__`
(`internal/bot/common/handlers/yandex_search.py:138-206`); handler class at line
66. The handler itself is registered in `HandlersManager` at
`internal/bot/common/handlers/manager.py:88`.

**Tool A — `web_search`** (`ToolName.WEB_SEARCH`, `internal/bot/constants.py:49`),
registration `yandex_search.py:138-179`, handler `self._llmToolWebSearch`. Current
parameters:

| name                   | type    | required | notes |
|------------------------|---------|----------|-------|
| `query`                | string  | yes      | |
| `return_page_content`  | boolean | yes      | |
| `enable_content_filter`| boolean | no       | default `false` |
| `max_results`          | number  | no       | doc says "Default: 3", **code default is `5`** — pre-existing drift, out of scope |

`web_search` has **no** `max_size` parameter today.

**Tool B — `get_url_content`** (`ToolName.GET_URL_CONTENT`,
`internal/bot/constants.py:50`), registration `yandex_search.py:181-206`,
handler `self._llmToolGetUrlContent`. Current parameters:

| name               | type    | required | notes |
|--------------------|---------|----------|-------|
| `url`              | string  | yes      | |
| `parse_to_markdown`| boolean | no       | default `true` |
| `max_size`         | number  | no       | default `10240` |

### 2.2 Handler signatures (verbatim, `yandex_search.py`)

```python
async def _llmToolWebSearch(  # line 224
    self,
    extraData: Optional[Dict[str, Any]],
    query: str,
    return_page_content: bool,
    enable_content_filter: bool = False,
    max_results: int = 5,
    **kwargs,
) -> str:
```

```python
async def _llmToolGetUrlContent(  # line 341
    self,
    extraData: Optional[Dict[str, Any]],
    *,
    url: str,
    parse_to_markdown: bool = True,
    max_size: int = 10240,
    **kwargs,
) -> str:
```

### 2.3 The condensing block (`yandex_search.py:428-449`, verbatim)

```python
if len(content) >= max_size:
    logger.debug(f"Content length is {len(content)} > {max_size}, condensing...")
    chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
    prompt = [
        ModelMessage(
            role="system",
            content=chatSettings[ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT].toStr(),
        ),
        ModelMessage(role="user", content=content),
    ]
    logger.debug(f"Will condense content of {url}...")
    mlRet = await self.llmService.generateText(
        prompt=prompt,
        chatId=ensuredMessage.recipient.id,
        chatSettings=chatSettings,
        modelKey=ChatSettingsKey.CHAT_MODEL,
        fallbackKey=ChatSettingsKey.CONDENSING_MODEL,
    )
    logger.debug(f"Condensed len is {len(mlRet.resultText)}")
    if mlRet.status == ModelResultStatus.FINAL and mlRet.resultText:
        content = mlRet.resultText
        await self.urlContentCondensedCache.set(condensedCacheKey, content)
```

Two load-bearing observations:

1. `chatSettings` is fetched **only inside this branch** (`yandex_search.py:430`),
   i.e. only when condensing is actually needed. The cache *lookup* at
   `yandex_search.py:384` happens earlier and does **not** have `chatSettings`
   available.
2. The system message uses the per-chat default prompt
   (`chatSettings[ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT].toStr()`,
   `yandex_search.py:434`).

### 2.4 The condensed cache (load-bearing for this design)

- `CacheType.URL_CONTENT_CONDENSED` = `"url_content_condensed"`
  (`internal/database/models.py:410`).
- Constructed at `yandex_search.py:214-219`:

  ```python
  self.urlContentCondensedCache = GenericDatabaseCache(
      database,
      namespace=CacheType.URL_CONTENT_CONDENSED,
      keyGenerator=JsonKeyGenerator[Dict[str, Any]](hash=False),
      valueConverter=StringValueConverter(),
  )
  ```

- **Today** the key generator is `JsonKeyGenerator(hash=False)`, so the stored key
  is the **literal sorted-JSON** of the key dict.
- Key dict is built at `yandex_search.py:383`:

  ```python
  condensedCacheKey = {"url": url, "max_size": max_size}
  ```

- Looked up **before** download (`yandex_search.py:384-386`), written **after** a
  successful condense (`yandex_search.py:449`).
- TTL is hardcoded `urlContentCacheTTL = 60 * 60` (1 hour, `yandex_search.py:220`).
- Background cleanup: `URL_CONTENT_CONDENSED` is in
  `AGGRESSIVE_CLEANUP_CACHE_TYPES` and gets a 7-day aggressive purge pass
  (`internal/bot/common/handlers/manager.py`, see `docs/llm/teamlead-memory.md`
  §"DB Cache Cleanup").

### 2.5 The `web_search → get_url_content` forwarding gap (`yandex_search.py:253-267`)

When `return_page_content=true`, `web_search` spawns a per-result
`asyncio.create_task` wrapping the inner `fetchUrlContent()`, which calls:

```python
content = await self._llmToolGetUrlContent(
    extraData=extraData, url=url, parse_to_markdown=True
)  # yandex_search.py:258
```

It forwards **neither** `max_size` (uses the default `10240`) **nor** any condensing
prompt. This design fixes the `max_size` gap and wires `condensing_prompt` through
the same call site.

### 2.6 `max_size` semantics (per-page)

`max_size` is compared against `len(content)` — i.e. **Python string length
(characters), not bytes**. The docstring at `yandex_search.py:361-362` says
"Maximum size of returned content in bytes", which is a pre-existing drift. Each
page in a `web_search` batch is condensed **independently** if it exceeds
`max_size`. See §9 (open questions) — the bytes-vs-chars drift is noted but **not
fixed** by this change.

---

## 3. Goals / Non-Goals

### Goals

1. Add an optional `condensing_prompt` parameter to **both** `web_search` and
   `get_url_content`.
2. Fall back to the per-chat `DOCUMENT_CONDENSING_PROMPT` when the parameter is
   absent, empty, or whitespace-only.
3. Correctly **differentiate cache entries** for distinct custom prompts.
4. **Fix the `max_size` forwarding gap**: add `max_size` to `web_search` and
   forward both `max_size` and `condensing_prompt` into each per-page
   `_llmToolGetUrlContent` call.
5. Preserve existing control flow and the "fetch `chatSettings` lazily, only when
   condensing is needed" ordering.

### Non-Goals

- Do **not** fix the `max_results` default inconsistency (doc "3" vs code `5`).
- Do **not** make the condensing threshold (`max_size`) configurable beyond what
  the existing parameter already allows.
- Do **not** resolve the `max_size` bytes-vs-chars docstring drift (noted in §9).
- Do **not** implement the "hash the resolved per-chat default prompt into the
  cache key" enhancement (see §4.5 / §9) — documented as a future option.
- No schema change, no new `ChatSettingsKey`, no new config key.

---

## 4. Design Decisions

### 4.1 Decision 1 — Switch the condensed cache to `JsonKeyGenerator(hash=True)`

The condensed cache key generator changes from
`JsonKeyGenerator[Dict[str, Any]](hash=False)` to
`JsonKeyGenerator[Dict[str, Any]](hash=True)`, and the key dict gains a
`condensing_prompt` field.

**Rationale.** With `hash=False` (today) the stored key is the literal JSON of the
dict, so adding a (potentially large) prompt string would bloat the stored key
without bound. With `hash=True` the stored key is a fixed-length hash, so the
prompt can be included in the key dict safely. The hash behavior is verified in §5.

**Accepted side effect.** This change **invalidates every currently-cached
condensed entry**, because the key representation changes from literal JSON to a
SHA512 hex digest. Given the 1-hour TTL (`yandex_search.py:220`) and the 7-day
aggressive cleanup, this is acceptable. Documented explicitly in §5.4.

### 4.2 Decision 2 — Add `condensing_prompt` to both tools; also forward `max_size`

`condensing_prompt` is added to `web_search` **and** `get_url_content`.
Independently, the pre-existing `max_size` gap is closed: `web_search` gains a
`max_size` parameter, and the `fetchUrlContent` call site forwards **both**
`max_size` and `condensing_prompt` into `_llmToolGetUrlContent`.

**Rationale.** `max_size` applies **per page** (each page is condensed
independently if it exceeds `max_size`), which is consistent with today's
per-page fetch semantics. Forwarding it lets a `web_search` caller cap per-page
size; today every batch page silently uses `10240`. The `max_results` default
drift is left untouched.

### 4.3 Decision 3 — Parameter name is `condensing_prompt` (snake_case)

Matches the established sibling tool-param convention (`return_page_content`,
`enable_content_filter`, `max_results`, `parse_to_markdown`, `max_size`). The
repo-wide rule is camelCase for Python identifiers, but LLM-tool-facing parameter
**names** in this handler are an established, intentional exception. All internal
Python identifiers introduced by this design (e.g. the normalization helper, the
local `normalizedCustomPrompt`) remain camelCase.

### 4.4 Decision 4 — Empty/None/whitespace normalization

`None`, the empty string `""`, and whitespace-only strings are all treated as
"use the default". Normalization is `.strip()`; if the stripped result is empty,
fall back to the per-chat `DOCUMENT_CONDENSING_PROMPT`.

**Rationale.** Models occasionally emit whitespace or an empty string for an
optional string param; treating those as "default" avoids accidental empty
condensing prompts (which would produce garbage). A dedicated helper makes the
rule explicit and unit-testable.

### 4.5 Decision 5 (recommendation) — Cache key uses the custom prompt **or `None`**, never the resolved default

The `condensing_prompt` field in the cache key dict is:

- the **stripped custom prompt** when one was supplied, **or**
- `None` when none was supplied (the default case).

The key dict **never** contains the resolved per-chat `DOCUMENT_CONDENSING_PROMPT`
value.

**Rationale (four points):**

1. **Correct differentiation.** Distinct custom prompts produce distinct key dicts
   → distinct SHA512 hashes → distinct cache entries.
2. **No regression for the default case.** Today the key is `{url, max_size}` and
   the default prompt is resolved at condense time, so two chats with *different*
   per-chat defaults already share one cache entry for the same `url`+`max_size`.
   Using `None` as the default sentinel preserves this exact behavior — default
   requests still collapse to a single entry per `(url, max_size)`.
3. **Preserves lazy `chatSettings`.** The cache lookup happens at
   `yandex_search.py:384`, **before** `chatSettings` is fetched (which only
   happens inside the condensing branch at `yandex_search.py:430`). Hashing the
   *resolved* default prompt would require fetching `chatSettings` for **every**
   cache lookup, including cache hits — a pointless cost and an ordering change.
   `None` needs no `chatSettings`.
4. **Accepted tradeoff (documented, not fixed).** Changing a chat's
   `DOCUMENT_CONDENSING_PROMPT` does **not** invalidate the default-prompt
   condensed cache until the 1h TTL expires — identical to today's behavior. The
   "fully correct" alternative (hash the resolved prompt, fetch `chatSettings`
   eagerly) is captured in §9 as a deferred enhancement.

---

## 5. Detailed Design

### 5.1 Verified: how `JsonKeyGenerator(hash=True)` produces a key

Source: `lib/cache/key_generator.py`. The class spans lines 121-209.

Constructor (`key_generator.py:151-180`):

```python
def __init__(self, *, sort_keys: bool = True, hash: bool = True):
    """Initialize JsonKeyGenerator with configuration options.

    Args:
        sort_keys: Whether to sort JSON keys for consistent serialization.
                   Defaults to True for deterministic hashing regardless of
                   dictionary key order.
        hash: Whether to create SHA512 hash of the JSON string.
              If False, returns the JSON string directly. Defaults to True
              for consistent key length and security.
    ...
    """
    self.sort_keys = sort_keys
    self.hash = hash
```

Key generation (`key_generator.py:182-209`):

```python
def generateKey(self, obj: K | Any) -> str:
    """Generate SHA512 hash from JSON-serialized object.

    Args:
        obj: K or Any object to convert to cache key.

    Returns:
        str: 128-character SHA512 hexadecimal hash if hash=True,
             otherwise the JSON string representation.
    ...
    """
    try:
        # Serialize to JSON with sorted keys for consistency
        jsonStr = utils.jsonDumps(obj, sort_keys=self.sort_keys)
    except (TypeError, ValueError):
        # Fallback to string representation if JSON serialization fails
        jsonStr = str(obj)

    # Create SHA512 hash
    if self.hash:
        return hashlib.sha512(jsonStr.encode("utf-8")).hexdigest()
    else:
        return jsonStr
```

**Confirmed properties** (critical, since the cache-key change depends on them):

| property | value | source |
|---|---|---|
| hash algorithm | **SHA-512** (NOT sha256/md5) | `key_generator.py:207` |
| encoding | UTF-8 of the JSON string | `key_generator.py:207` (`jsonStr.encode("utf-8")`) |
| output | hex digest | `key_generator.py:207` (`.hexdigest()`) |
| output length | **128 hex characters** | SHA-512 hexdigest |
| key ordering | sorted (`sort_keys=True` default) | `key_generator.py:151`, `:200` |
| determinism | fully deterministic — pure function of the UTF-8 bytes; stable across runs, processes, and platforms | SHA-512 spec |
| `None` handling | serializes to JSON `null` via `utils.jsonDumps` (not the fallback branch — `None` is JSON-serializable) | `key_generator.py:200` |
| non-serializable fallback | `str(obj)` | `key_generator.py:201-203` |

So the new key dict

```python
{"url": url, "max_size": max_size, "condensing_prompt": normalizedCustomPrompt}
```

serializes (with sorted keys) to e.g.
`'{"condensing_prompt": null, "max_size": 10240, "url": "https://example.com"}'`
(default case) and is then SHA-512-hashed to a stable 128-char hex string. Including
the prompt never bloats the stored key.

### 5.2 New `LLMFunctionParameter` entries

`LLMFunctionParameter` shape (`lib/ai/models.py:294-318`):
`LLMFunctionParameter(name, description, type, required, extra={})`.
`LLMParameterType` members include `STRING`/`NUMBER`/`BOOLEAN`/`ARRAY`/`OBJECT`
(`lib/ai/models.py:253-274`).

**Add to `get_url_content`** (`yandex_search.py:181-206`):

```python
LLMFunctionParameter(
    name="condensing_prompt",
    description=(
        "Optional instructions that override the default condensing prompt when "
        "the page content exceeds max_size. Use this to tailor what the condenser "
        "keeps (e.g. 'extract only the recipe and ingredients', "
        "'summarize the financial figures'). Ignored when content fits within "
        "max_size. Empty or whitespace-only falls back to the default condensing "
        "behaviour (a detailed retelling of the document)."
    ),
    type=LLMParameterType.STRING,
    required=False,
),
```

**Add to `web_search`** (`yandex_search.py:138-179`) — two new params. Note
`max_size` is new to `web_search`:

```python
LLMFunctionParameter(
    name="max_size",
    description=(
        "Max size of returned content PER PAGE. Each fetched page is independently "
        "condensed if it exceeds this size. Only relevant when "
        "return_page_content is true. (Default: 10240)"
    ),
    type=LLMParameterType.NUMBER,
    required=False,
),
LLMFunctionParameter(
    name="condensing_prompt",
    description=(
        "Optional instructions that override the default condensing prompt for "
        "each fetched page that exceeds max_size (only relevant when "
        "return_page_content is true). Lets you tailor what the condenser keeps, "
        "e.g. 'extract only the recipe and ingredients'. Empty or whitespace-only "
        "falls back to the default condensing behaviour."
    ),
    type=LLMParameterType.STRING,
    required=False,
),
```

### 5.3 Updated handler signatures

```python
async def _llmToolWebSearch(
    self,
    extraData: Optional[Dict[str, Any]],
    query: str,
    return_page_content: bool,
    enable_content_filter: bool = False,
    max_results: int = 5,
    condensing_prompt: Optional[str] = None,   # NEW
    max_size: int = 10240,                      # NEW (closes the forwarding gap)
    **kwargs: Any,
) -> str:
```

```python
async def _llmToolGetUrlContent(
    self,
    extraData: Optional[Dict[str, Any]],
    *,
    url: str,
    parse_to_markdown: bool = True,
    max_size: int = 10240,
    condensing_prompt: Optional[str] = None,   # NEW
    **kwargs: Any,
) -> str:
```

Notes:

- `condensing_prompt` is typed `Optional[str]` and defaults to `None`.
- `**kwargs: Any` is made explicit (was bare `**kwargs`); AGENTS.md requires type
  hints. The tool-handler contract is `async def _llmTool*(self, extraData,
  <params>, **kwargs)` — see `.agents/skills/add-llm-tool/SKILL.md`.
- These handlers currently `-> str`; that is a **pre-existing** deviation from the
  `-> Dict[str, Any]` contract and is **not** in scope for this change.

### 5.4 Normalization helper

A small private method on the handler:

```python
@staticmethod
def _normalizeCondensingPrompt(prompt: Optional[str]) -> Optional[str]:
    """Normalize a caller-supplied condensing prompt.

    Treats ``None``, the empty string, and whitespace-only strings as
    "use the default" (returns ``None``). Otherwise returns the stripped
    prompt.

    Args:
        prompt: The raw condensing prompt from the tool call (may be ``None``).

    Returns:
        The stripped prompt, or ``None`` when the caller did not supply a
        usable prompt.
    """
    if prompt is None:
        return None
    stripped = prompt.strip()
    return stripped or None
```

Called once per `_llmToolGetUrlContent` invocation, **before** the cache lookup
(so the key dict uses the normalized value). The `_llmToolWebSearch` path
normalizes once and forwards the normalized value into each per-page call (the
per-page call still re-normalizes defensively, which is cheap and idempotent).

### 5.5 New flow inside `_llmToolGetUrlContent`

Replace the key-dict construction at `yandex_search.py:383` and the condensing
block at `yandex_search.py:428-449`. Sketch (full lines in implementation):

```python
# After ensuredMessage validation, BEFORE the cache lookup:
normalizedCustomPrompt = self._normalizeCondensingPrompt(condensing_prompt)

# Cache key now carries the normalized prompt (or None).
condensedCacheKey = {
    "url": url,
    "max_size": max_size,
    "condensing_prompt": normalizedCustomPrompt,
}
content = await self.urlContentCondensedCache.get(condensedCacheKey, self.urlContentCacheTTL)
if content is not None:
    return content

# ... (download + markdown conversion unchanged) ...

if len(content) >= max_size:
    logger.debug(f"Content length is {len(content)} > {max_size}, condensing...")
    chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
    effectivePrompt = (
        normalizedCustomPrompt
        if normalizedCustomPrompt is not None
        else chatSettings[ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT].toStr()
    )
    prompt = [
        ModelMessage(role="system", content=effectivePrompt),
        ModelMessage(role="user", content=content),
    ]
    logger.debug(f"Will condense content of {url}...")
    mlRet = await self.llmService.generateText(
        prompt=prompt,
        chatId=ensuredMessage.recipient.id,
        chatSettings=chatSettings,
        modelKey=ChatSettingsKey.CHAT_MODEL,
        fallbackKey=ChatSettingsKey.CONDENSING_MODEL,
    )
    logger.debug(f"Condensed len is {len(mlRet.resultText)}")
    if mlRet.status == ModelResultStatus.FINAL and mlRet.resultText:
        content = mlRet.resultText
        await self.urlContentCondensedCache.set(condensedCacheKey, content)

return content
```

Key points:

- `normalizedCustomPrompt` is computed **before** the cache lookup, so the key
  dict is consistent between lookup and set.
- `chatSettings` is still fetched **only inside the condensing branch** — the lazy
  ordering from §2.3 is preserved.
- `effectivePrompt` selects the custom prompt when present, else the per-chat
  default. This is the **only** consumer of `normalizedCustomPrompt` beyond the
  cache key.

### 5.6 Cache constructor change (`yandex_search.py:214-219`)

```python
self.urlContentCondensedCache = GenericDatabaseCache(
    database,
    namespace=CacheType.URL_CONTENT_CONDENSED,
    keyGenerator=JsonKeyGenerator[Dict[str, Any]](hash=True),   # was hash=False
    valueConverter=StringValueConverter(),
)
```

**Cache invalidation note.** Switching `hash=False` → `hash=True` changes every
stored key from literal JSON to a 128-char SHA-512 hex digest. Existing rows are
therefore unreachable. They expire via the 1h TTL (`yandex_search.py:220`) and are
purged within 7 days by the aggressive cleanup pass
(`AGGRESSIVE_CLEANUP_CACHE_TYPES`, `docs/llm/teamlead-memory.md` §"DB Cache
Cleanup"). No manual migration is required or recommended.

### 5.7 `web_search` forwarding (`yandex_search.py:253-267`)

The inner `fetchUrlContent` closure gains the forwarded args. The call site at
`yandex_search.py:258` becomes:

```python
content = await self._llmToolGetUrlContent(
    extraData=extraData,
    url=url,
    parse_to_markdown=True,
    max_size=max_size,                 # NEW — closes the gap
    condensing_prompt=condensing_prompt,  # NEW
)
```

`max_size` and `condensing_prompt` are the `web_search` parameters (already
normalized once at the top of `_llmToolWebSearch` if desired; re-normalized
defensively inside `_llmToolGetUrlContent`). The `web_search`-level normalization
is optional but reduces repeated work across the batch; the per-call
re-normalization is the source of truth.

### 5.8 Never-raise contract

Both handlers already wrap their bodies in `try/except` returning a JSON error
(`yandex_search.py:337-339`, `:453-455`). The new code path (normalization, prompt
selection) contains no I/O and cannot realistically raise; it stays inside the
existing `try` block. No new error path is needed. See
`.agents/skills/add-llm-tool/SKILL.md` for the never-raise contract.

---

## 6. Files to Change

| path | change |
|---|---|
| `internal/bot/common/handlers/yandex_search.py` | (1) `web_search` registration: add `max_size` + `condensing_prompt` `LLMFunctionParameter`s (`:147-177`). (2) `get_url_content` registration: add `condensing_prompt` `LLMFunctionParameter` (`:184-204`). (3) Both handler signatures (`:224-232`, `:341-349`). (4) New `_normalizeCondensingPrompt` static method. (5) Cache ctor `hash=False`→`hash=True` (`:214-219`). (6) Key-dict + condensing block (`:383`, `:428-449`). (7) `fetchUrlContent` forwarding (`:258`). |
| `tests/bot/common/handlers/test_yandex_search.py` | **NEW FILE** — no yandex test exists today (verified: `tests/**/*yandex*` has no matches). Mirror layout per AGENTS.md (`tests/bot/common/handlers/`). |
| `CHANGELOG.md` | One line under `## [Unreleased]` → **Added** (see §8). |

### Docs surfaces reviewed for cache-key-format mentions

I grepped `docs/` for the cache key *shape* (`url_content_condensed`,
`condensedCacheKey`, etc.). The condensed cache is referenced **only** by its
namespace name and cleanup TTL — the actual key dict shape `{"url", "max_size"}`
is **not documented anywhere**. Therefore the `hash=False`→`hash=True` switch and
the added `condensing_prompt` field require **no** doc edit for the key format.
Relevant (unchanged) references for completeness:

- `docs/database-schema.md:711`, `:1066`
- `docs/database-schema-llm.md:718`
- `docs/llm/database.md:56`
- `docs/llm/teamlead-memory.md:30,33,34`
- `docs/llm/handlers.md` and `docs/llm/libraries.md` — do not enumerate the
  per-tool parameter lists or the cache key shape (verified by grep); no edit
  needed for this change.

---

## 7. Test Plan

Grounded in the actual sibling test style
(`tests/bot/common/handlers/test_chat_search.py`): module docstring, `from
unittest.mock import AsyncMock, Mock, patch`, local `_makeChatSettings` /
`_makeEnsuredMessage` helpers building real `ChatSettingsValue(...)` /
`EnsuredMessage` objects, class-based test groups, `asyncio_mode = "auto"` (no
decorator). Shared autouse fixtures (singleton reset etc.) come from
`tests/conftest.py`. Construct a real `YandexSearchHandler` via the same
mocked-`ConfigManager`/`Database`/`BotProvider` pattern, then stub
`llmService.generateText`, the two caches, and `getChatSettings` at the instance
level.

Target cases (new file `tests/bot/common/handlers/test_yandex_search.py`):

| # | case | assertion |
|---|---|---|
| a | custom prompt supplied, content > `max_size` | mock `llmService.generateText`; assert the system `ModelMessage.content` equals the **stripped** custom prompt; assert cache `.set` called with a key whose `condensing_prompt` == stripped prompt. |
| b | `condensing_prompt=None`, content > `max_size` | assert system message == the per-chat `DOCUMENT_CONDENSING_PROMPT` default; assert key dict `condensing_prompt == None`. |
| c | `condensing_prompt=""`, content > `max_size` | same as (b) — default used, key `condensing_prompt == None`. |
| d | `condensing_prompt="   "` (whitespace), content > `max_size` | same as (b). |
| e | two distinct custom prompts, same `url`+`max_size` | assert the two computed `condensedCacheKey` dicts differ; with `hash=True` their `JsonKeyGenerator(...).generateKey(...)` digests differ (direct unit test on the generator is fine here). |
| f | `web_search(return_page_content=True, condensing_prompt=..., max_size=...)` | stub `_llmToolGetUrlContent`; assert it is called with `condensing_prompt=` and `max_size=` forwarded (closes the gap). Use `assert_called_with_partial` from `tests/utils.py`. |
| g | cache hit (same `url`+`max_size`+prompt) | pre-seed `urlContentCondensedCache.get` to return a value; assert `_downloadUrl` and `generateText` are **not** called, and the cached value is returned. |
| h | `_normalizeCondensingPrompt` unit cases | `None`→`None`, `""`→`None`, `"  "`→`None`, `"  hi  "`→`"hi"`, `"hi"`→`"hi"`. |
| i | content ≤ `max_size` | `condensing_prompt` is **ignored** (no `generateText` call) regardless of value; custom prompt never reaches the cache key because no condense happens — assert cache `.set` not called. |

The key-digest assertion in (e) can construct the generator directly:

```python
from lib.cache import JsonKeyGenerator

gen = JsonKeyGenerator[Dict[str, Any]](hash=True)
k1 = gen.generateKey({"url": "u", "max_size": 10240, "condensing_prompt": "recipe"})
k2 = gen.generateKey({"url": "u", "max_size": 10240, "condensing_prompt": "finances"})
assert k1 != k2
assert len(k1) == 128 and len(k2) == 128  # SHA-512 hex
```

---

## 8. Docs / CHANGELOG Impact

**CHANGELOG.md** — add one line under `## [Unreleased]` → **Added** (format per
`docs/llm/changelog.md`):

> Added optional `condensing_prompt` parameter to the `web_search` and
> `get_url_content` LLM tools (overrides the default document-condensing prompt
> per call), and forwarded `max_size` from `web_search` to per-page content fetches.

**Project docs** — no `docs/llm/handlers.md`, `docs/llm/libraries.md`,
`docs/database-schema.md`, or `docs/database-schema-llm.md` edit is required: none
of them enumerate these tools' parameters or the condensed-cache key shape
(verified by grep, §6). The post-implementation pass should still run
`make check-docs` and load the `update-project-docs` skill to confirm nothing
else drifted.

---

## 9. Open Questions / Alternatives Considered

1. **Hash the resolved per-chat default prompt into the cache key.** *Deferred.*
   Would make "change a chat's `DOCUMENT_CONDENSING_PROMPT`" immediately
   invalidate that chat's default-prompt condensed entries, but requires fetching
   `chatSettings` on **every** cache lookup (including hits), changing the lazy
   ordering in §2.3. Not worth the cost given the 1h TTL. Documented as accepted
   tradeoff in §4.5.

2. **Expose a configurable condensing threshold separate from `max_size`.**
   *Deferred.* `max_size` already serves as both the return-size cap and the
   condense trigger; splitting them adds surface area with no demonstrated need.

3. **`max_size` bytes-vs-chars docstring drift** (`yandex_search.py:361-362`
   says "in bytes", code compares `len(content)` which is characters). *Noted,
   not fixed.* A separate, focused fix should correct the docstring (and decide
   the intended semantics) — out of scope here to avoid bundling unrelated
   changes.

4. **`max_results` default drift** (docstring "Default: 3" vs code `5`). *Out of
   scope*, explicitly per the brief.

5. **`-> str` vs `-> Dict[str, Any]` return-type contract drift** on both
   handlers. *Pre-existing, out of scope.* A separate cleanup should reconcile
   these with the tool-handler contract documented in
   `.agents/skills/add-llm-tool/SKILL.md`.

6. **Should `web_search` normalize once and forward the normalized value, or
   forward raw and let `_llmToolGetUrlContent` normalize?** Design forwards the
   raw `web_search` params and lets `_llmToolGetUrlContent` be the single source
   of truth for normalization. This keeps `_llmToolGetUrlContent` correct when
   called directly and avoids two normalization sites that could drift.

---

## 10. Implementation Phasing

This change is small (≤3 files, clear design) and fits a **single
`software-developer` phase**. Suggested ordering within that phase:

1. **Code** — cache ctor (`hash=True`), both registrations, both signatures,
   `_normalizeCondensingPrompt`, condensing-block + key-dict rewrite,
   `fetchUrlContent` forwarding. (One coherent edit to
   `internal/bot/common/handlers/yandex_search.py`.)
2. **Tests** — new `tests/bot/common/handlers/test_yandex_search.py` covering
   cases (a)-(i). Per AGENTS.md, write tests that exercise the new behaviour
   (custom-prompt path, normalization, cache-key differentiation, forwarding).
3. **Quality gates** — `make format lint` then `make test` (mandatory; see
   `.agents/skills/run-quality-gates/SKILL.md`).
4. **Docs** — CHANGELOG line (§8); run `make check-docs`; load
   `update-project-docs` skill for the final confirmation pass.

This is comfortably within the ~60-step budget guidance for a focused,
well-specified change.

---

## 11. Quick reference — cited source locations

| what | where |
|---|---|
| `YandexSearchHandler` class | `internal/bot/common/handlers/yandex_search.py:66` |
| `web_search` registration | `yandex_search.py:138-179` |
| `get_url_content` registration | `yandex_search.py:181-206` |
| `_llmToolWebSearch` signature | `yandex_search.py:224-232` |
| `_llmToolGetUrlContent` signature | `yandex_search.py:341-349` |
| `fetchUrlContent` forwarding gap | `yandex_search.py:253-267` (call at `:258`) |
| condensed cache constructor | `yandex_search.py:214-219` |
| `urlContentCacheTTL = 60*60` | `yandex_search.py:220` |
| `condensedCacheKey` build | `yandex_search.py:383` |
| cache lookup (pre-download) | `yandex_search.py:384-386` |
| condensing block | `yandex_search.py:428-449` |
| lazy `chatSettings` fetch | `yandex_search.py:430` |
| default prompt consumer | `yandex_search.py:434` |
| `JsonKeyGenerator` class | `lib/cache/key_generator.py:121-209` |
| SHA-512 hash branch | `lib/cache/key_generator.py:206-207` |
| `LLMParameterType` enum | `lib/ai/models.py:253-274` |
| `LLMFunctionParameter` ctor | `lib/ai/models.py:294-318` |
| `ToolName.WEB_SEARCH` / `GET_URL_CONTENT` | `internal/bot/constants.py:49-50` |
| `CacheType.URL_CONTENT_CONDENSED` | `internal/database/models.py:410` |
| `ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT` | `internal/bot/models/chat_settings.py:340` |
| default prompt TOML | `configs/00-defaults/bot-defaults.toml:250-254` |
| handler registration in manager | `internal/bot/common/handlers/manager.py:88` |
