---
category: reference
---

# LLM User-Message Format (verified 2026-07-18)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

Real user messages are rendered as **JSON strings** in `role="user"` ModelMessages, NOT plain text. This is documented to the LLM in `chat-prompt-suffix` (`configs/00-defaults/bot-defaults.toml`), on the `BOT_OWNER_SYSTEM` settings page (bot-owner-only, so chat admins can't clobber the format instructions). The suffix enumerates the keys.

- **`EnsuredMessage.formatForLLM`** (`internal/bot/models/ensured_message.py`) JSON branch builds `{login, name, date, messageId, type, text, replyId, quote, mediaDescription, userMemories}` — **falsy values DROPPED**, serialized via `utils.jsonDumps(ret, compact=False)`. TEXT branch = plain text w/ `<media-description>`/`<quote>` tags. `formatForLLM` itself only accepts `JSON`/`TEXT` (raises `ValueError` otherwise); `LLMMessageFormat.SMART` is resolved one layer up in `toModelMessage`, which picks TEXT for `role="assistant"` and JSON otherwise before calling `formatForLLM`. Render entry points `toModelMessage`/`toModelMessageList` (and `formatForLLM` itself) take keyword-only `cache` (REQUIRED — no default) and `excludeMemoryIds` (optional, defaults to `None`, coerced to an empty set internally) — ADR-018 (see [`memories/memories-context-dedup.md`](memories-context-dedup.md)).
- Condensed summaries + `randomContext` are also rendered as JSON via `renderCondensedSummary` per ADR-019 (see [`memories/condensed-context-retrieval.md`](condensed-context-retrieval.md)) — the former raw-text-in-user-role asymmetry was resolved 2026-07-12.
- `CHAT_PROMPT`/`CHAT_PROMPT_SUFFIX` are `ChatSettingsKey` enum values (`internal/bot/models/chat_settings.py`), NOT module-level Python constants. Read from merged TOML at runtime. Concatenated at every system-message site.
