# Condensing Prompt Split

> **Status:** Implemented

## Problem

The condensing prompt (`condensing-prompt`) serves a confused dual role. In
`internal/services/llm/service.py:461-466` the same string is used as both
the system message (fallback when no system prompt exists) and the final user
message:

```python
systemMessage = ModelMessage(role="system", content=condensingPrompt) if systemPrompt is None else systemPrompt
condensingMessage = ModelMessage(role="user", content=condensingPrompt)
```

In practice `systemPrompt` is **never None** because `ret` always starts with
the chat personality prompt (`base.py:701-708`). So the condensing model
actually receives:

```
[system]  chat-prompt + chat-prompt-suffix    <-- the CHAT personality, not a condensing instruction
[user]    message 1
[assistant] reply 1
[user]    message 2
...
[user]    condensing-prompt                   <-- the actual instruction
```

Two problems:

1. **Wrong system identity.** The condensing model thinks it is the chat
   persona (e.g. "Ты - Принни: вайбовый пингвин"), then gets asked to
   summarize. The persona pollutes the summarization.
2. **Same text in two roles.** The condensing prompt text is dumped as both
   system and user message when `systemPrompt is None` (the rare path), which
   is incoherent.

## Solution

Split into two settings with clean role separation:

- `condensing-system-prompt` -- standing identity and rules (who the model is
  during condensing).
- `condensing-prompt` -- per-call task trigger ("summarize this batch").

### New prompts

**`condensing-system-prompt`** (new setting):

```
Ты сжимаешь историю переписки для передачи в другой LLM-контекст.
Сохрани максимум фактов: темы, цифры, даты, имена, названия, ссылки,
решения, атрибуцию (кто что говорил), открытые вопросы.
Пиши связным текстом, группируя по темам. Без шаблонов и заголовков-секций.
Пиши на языке переписки. Без вводных слов и пояснений — только содержание.
```

**`condensing-prompt`** - existing setting

### What the condensing model will receive

```
[system]  condensing-system-prompt            <-- clean condensing identity
[user]    message 1
[assistant] reply 1
[user]    message 2
...
[user]    condensing-prompt                   <-- minimal trigger
```

## Implementation Steps

### Step 1: Add `ChatSettingsKey` and metadata

**File:** `internal/bot/models/chat_settings.py`

1. Add `CONDENSING_SYSTEM_PROMPT = "condensing-system-prompt"` to the
   `ChatSettingsKey` enum (near the existing `CONDENSING_PROMPT` entry).
2. Add a `_chatSettingsInfo` entry for the new key (same page/group as
   `CONDENSING_PROMPT`).

### Step 2: Add default values in config

**Files:**
- `configs/00-defaults/bot-defaults.toml`
- `configs/common/01-bot-defaults.toml`

1. Add `condensing-system-prompt` with the new system prompt text.
2. Replace the existing `condensing-prompt` value with the shortened version.

### Step 3: Update `condenseContext` in LLM service

**File:** `internal/services/llm/service.py`

1. Add a `condensingSystemPrompt` parameter to `condenseContext()`:

   ```python
   async def condenseContext(
       self,
       messages: Sequence[ModelMessage],
       model: AbstractModel,
       *,
       keepFirstN: int = 0,
       keepLastN: int = 1,
       condensingModel: Optional[AbstractModel] = None,
       condensingPrompt: Optional[str] = None,
       condensingSystemPrompt: Optional[str] = None,  # NEW
       maxTokens: Optional[int] = None,
   ) -> Sequence[ModelMessage]:
   ```

2. Replace the current message construction logic (lines ~461-466):

   **Before:**

   ```python
   systemMessage = ModelMessage(role="system", content=condensingPrompt) if systemPrompt is None else systemPrompt
   condensingMessage = ModelMessage(role="user", content=condensingPrompt)
   ```

   **After:**

   ```python
   # Prefer the dedicated condensing system prompt over the chat persona.
   if condensingSystemPrompt is not None:
       systemMessage = ModelMessage(role="system", content=condensingSystemPrompt)
   elif systemPrompt is not None:
       systemMessage = systemPrompt
   else:
       systemMessage = ModelMessage(
           role="system",
           content=(
               "You condense conversation history for another LLM context."
               " Preserve maximum facts: topics, numbers, dates, names,"
               " decisions, attribution, open questions."
               " Write in the language of the conversation."
           ),
       )
   condensingMessage = ModelMessage(role="user", content=condensingPrompt)
   ```

   Key change: when `condensingSystemPrompt` is provided, it replaces the
   chat personality system prompt entirely. The condensing model should NOT
   think it is the chat persona.

3. Update the fallback for `condensingPrompt` (lines ~454-460) -- keep as is,
   it's the per-call trigger.

### Step 4: Update callers of `condenseContext`

**File:** `internal/bot/common/handlers/base.py`

Pass the new `condensingSystemPrompt` at every call site (lines ~794-801,
~818-825):

```python
condensedRet = await self.llmService.condenseContext(
    ret,
    model=llmModel,
    keepFirstN=keepFirstN,
    keepLastN=keepLastN,
    maxTokens=maxTokens,
    condensingModel=chatSettings[ChatSettingsKey.CONDENSING_MODEL].toModel(self.llmManager),
    condensingPrompt=chatSettings[ChatSettingsKey.CONDENSING_PROMPT].toStr(),
    condensingSystemPrompt=chatSettings[ChatSettingsKey.CONDENSING_SYSTEM_PROMPT].toStr(),
)
```

### Step 5: Update tests

1. Add `CONDENSING_SYSTEM_PROMPT` to test fixtures that build
   `chatSettings` dicts.
2. Verify existing condensing tests still pass (the new system prompt should
   produce similar or better summaries).
3. Add a test that the condensing model receives the condensing system prompt,
   not the chat personality prompt.

### Step 6: Update documentation

Using the `update-project-docs` skill after implementation:

| Doc | What changes |
|---|---|
| `docs/llm/configuration.md` | New `condensing-system-prompt` setting |
| `docs/llm/services.md` | `condenseContext` parameter change |
| `docs/database-schema.md` | New setting key in chat settings reference |
| `docs/database-schema-llm.md` | Same, keep in sync |

## Risks and Open Questions

- **Backward compatibility:** Existing deployments that don't set
  `condensing-system-prompt` will fall through to the chat personality system
  prompt (current behavior). The `condensingSystemPrompt` parameter defaults
  to `None`, so nothing breaks without config changes.
- **Condensed cache messages** are stored with `role="system"`
  (`base.py:759`). After this change they'll sit alongside the new
  condensing system prompt. This is fine -- they're factual summaries, and
  the condensing system prompt doesn't conflict with them.
- **The `condenseContext` fallback path** (`systemPrompt is None` and
  `condensingSystemPrompt is None`) gets a hardcoded English system prompt.
  This mirrors the existing hardcoded English fallback for `condensingPrompt`
  and is acceptable as a last resort.
