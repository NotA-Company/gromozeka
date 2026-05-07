# Divination Handler — Brief Plan

> **Companion to:** [`divination-handler-plan.md`](divination-handler-plan.md) (full design).
> **Audience:** quick-glance overview for reviewers / future-you.

---

## What

Add tarot & runes readings to the bot:

- **Slash commands:** `/taro <layout> [question]`, `/runes <layout> [question]`
  (aliases: `/tarot`, `/таро`, `/rune`, `/руны`).
- **LLM tools:** `do_tarot_reading`, `do_runes_reading` so the model can throw
  the cards/runes when the user asks naturally.

Pipeline per reading: parse layout → draw N unique symbols (with reversals for
tarot) → LLM interprets → optional spread image → reply (photo + caption +
follow-up text if needed) → persist to DB.

---

## Where

```
lib/divination/                                 # all logic, depends ONLY on lib/ai
  base.py          BaseDivinationSystem (ABC), Symbol, DrawnSymbol, Reading
  layouts.py       Layout dataclass + LayoutRegistry
  drawing.py       drawSymbols(...) — wraps random.sample, single RNG entry point
  localization.py  English → {lang: localised} maps for symbols/positions/layouts
  tarot.py         TarotSystem      (supportsReversed=True)
  runes.py         RunesSystem      (supportsReversed=False)
  decks/
    tarot_rws.py            78-card Rider–Waite–Smith (English source-of-truth)
    runes_elder_futhark.py  24 Elder Futhark runes

internal/bot/common/handlers/divination.py      # one handler, both systems
internal/database/repositories/divinations.py   # insert-only repo (v1)
internal/database/migrations/versions/migration_014_*.py
```

> **AI boundary:** `lib/divination` imports from `lib/ai` only (e.g.
> `ModelMessage`). It MUST NOT touch `internal/services/llm`. The handler
> is the sole caller of `LLMService.generateText` / `generateImage`.

> **Naming:** English is the source of truth on `Symbol`, `Layout`,
> position. Russian (and any future language) lives in
> `lib/divination/localization.py` as plain dicts; `tr()` falls back to
> English when missing.

Subclassing `BaseDivinationSystem` is how we add I-Ching, Lenormand, etc. later.

---

## Layouts (v1, predefined only)

| System | Layouts |
|---|---|
| Tarot  | `one_card`, `three_card`, `celtic_cross`, `relationship`, `yes_no` |
| Runes  | `one_rune`, `three_runes` (Norns), `five_runes`, `nine_runes` |

Aliases (en/ru/numeric) resolve case- and separator-insensitively. Unknown
layout names are **rejected with the supported list** in v1; the LLM-based
shape inference is a stub (`_llmGetUnknownLayoutShape`, TODO until `lib/ai`
supports structured output).

---

## LLM Integration

- **Interpretation:** `LLMService.generateText(...)` with a system prompt and
  user-message template both pulled from `ChatSettingsKey` (see below). The
  template instructs the model to reply in the question's language.
- **Image:** `LLMService.generateImage(prompt)` rendered from another
  `ChatSettingsKey` template — one image per spread. On failure, fall through
  to text-only. Caption truncated to Telegram limit; overflow goes into a
  follow-up text message.
- **Tools:** registered with `LLMService.registerTool(...)`, gated by
  `divination.tools-enabled`. Default to text-only; LLM opts in to image via
  `generate_image=true`.

---

## Configuration

```toml
[divination]
enabled = false                 # gated; conditional registration in HandlersManager
tarot-enabled = true
runes-enabled = true
image-generation = true
tools-enabled = true

[divination.tarot]
allow-reversed = true

[divination.runes]
allow-reversed = false
```

No prompt text in `[divination]` — all prompts/templates are chat settings.

New `ChatSettingsKey` entries (TOML-key form in `[bot.defaults]`):

| Enum                                | TOML key                          | Page              | Purpose |
|-------------------------------------|-----------------------------------|-------------------|---------|
| `TAROT_SYSTEM_PROMPT`               | `tarot-system-prompt`              | LLM_BASE          | Tarot interpretation system prompt |
| `RUNES_SYSTEM_PROMPT`               | `runes-system-prompt`             | LLM_BASE          | Runes interpretation system prompt |
| `DIVINATION_USER_PROMPT_TEMPLATE`   | `divination-user-prompt-template` | BOT_OWNER_SYSTEM  | User-message template; placeholders `{userName}`, `{question}`, `{layoutName}`, `{positionsBlock}`, `{cardsBlock}` |
| `DIVINATION_IMAGE_PROMPT_TEMPLATE`  | `divination-image-prompt-template`| BOT_OWNER_SYSTEM  | Image-prompt template; placeholders `{layoutName}`, `{spreadDescription}`, `{styleHint}` |

Default values for all four ship via `configs/00-defaults/` under
`[bot.defaults]`, alongside the existing `chat-prompt` / `summary-prompt`
defaults. No prompt strings live in Python.

---

## Persistence (migration 014)

Single new table `divinations` — insert-only in v1, no `/lastreadings`.
Composite primary key `(chat_id, message_id)` (matches `chat_messages`,
no `AUTOINCREMENT`).

```
chat_id (PK), message_id (PK), user_id,
system_id, deck_id, layout_id,
question, draws_json, interpretation,
image_prompt, media_id, rng_seed, invoked_via, created_at
```

- `media_id` is an FK-by-comment to `media_attachments.file_unique_id` —
  same convention as `chat_messages.media_id`. Image **bytes** are managed
  by the existing media pipeline / `StorageService`; the divinations row
  only holds the link.
- `created_at` set explicitly by the app (no `DEFAULT CURRENT_TIMESTAMP` —
  migration 013 rule).
- One index: `(chat_id, user_id, created_at)`. No standalone time-only index.
- DB failure must NOT block the user reply: log and continue.

---

## Rate Limiting

Reuse `LLMService.rateLimit(chatId, chatSettings)` once per command. No new
limiter queue.

---

## Testing

- **Unit (collocated)** in `lib/divination/`: deck integrity, layout alias
  resolution, drawing determinism with seeded RNG, ~50% reversal rate sanity,
  localization fallback, template-rendering placeholder substitution.
- **Handler tests** in `tests/bot/test_divination_handler.py` with the
  existing `mockBot`, `mockConfigManager`, `testDatabase`, `mockLLMService`
  fixtures.
- **Golden tests** in `tests/divination/golden/` via `lib/aurumentation`
  (record once, CI replays — no live API calls).

---

## Implementation Order (11 steps)

1. `lib/divination` skeleton (`base`, `layouts`, `drawing`, `localization`)
   + unit tests. Imports from `lib/ai` only.
2. Populate decks + Russian localization + integrity tests.
3. `TarotSystem` / `RunesSystem` + template-rendering tests.
4. Migration 014 + `DivinationsRepository` (composite PK, `media_id` link)
   + schema test.
5. New `ChatSettingsKey` entries + default prompt strings under
   `configs/00-defaults/`.
6. `DivinationHandler` (commands only, text-only) + wire into
   `HandlersManager` behind config flag.
7. Image generation step (insert into `media_attachments`, link via
   `media_id`).
8. Register LLM tools (`do_tarot_reading`, `do_runes_reading`).
9. Wire persistence into the handler (log-and-swallow on failure).
10. Golden tests via `lib/aurumentation`.
11. Update docs (`docs/llm/handlers.md`, `docs/llm/configuration.md`,
    `docs/database-schema*.md`) using the `update-project-docs` skill.

`make format lint && make test` after each step.

---

## Out of Scope (v1)

Other divination systems, multi-turn ("draw one more"), `/lastreadings`,
configurable reversal probability, structured-output for unknown layouts,
sharing readings, per-user stats.
