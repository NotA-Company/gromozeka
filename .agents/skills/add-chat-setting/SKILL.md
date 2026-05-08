---
name: add-chat-setting
description: >
  Recipe for adding a new chat setting to Gromozeka correctly, covering all
  four sites that must change together — the `ChatSettingsKey` enum value, the
  `_chatSettingsInfo` TypedDict entry, the default value in the right TOML
  config file, and any consumer code that reads it. Encodes the `tasks.md §4.1`
  CRITICAL lesson: missing any of these leaves a setting half-wired and
  non-functional. Also covers the `getChatSettings()` tuple-return gotcha and
  the keyword-only `updatedBy` requirement. Triggers: add chat setting, new
  chat setting, settings key, per-chat config, ChatSettingsKey.
---

# Add a Chat Setting

## When to use

- Exposing a new user-configurable value per chat (prompt, flag, model selection, numeric threshold, etc.).
- Promoting an existing hardcoded constant to a per-chat override.

## When NOT to use

- The value is **global**, not per-chat → it's a normal config key. Load `read-project-docs` and update `configs/00-defaults/*.toml` + `ConfigManager` + `docs/llm/configuration.md` instead.
- The value is **per-user**, not per-chat → different data model; see `internal/database/` repositories.

## Why this skill exists

`docs/llm/tasks.md` §4.1 flags this as CRITICAL because every site below must change together. Missing any one leaves the setting half-wired: either it doesn't appear in `/settings`, or it appears but has no default value and crashes when consumed.

There are **four** sites. All four.

## Site 1 — Add the enum value

File: [`internal/bot/models/chat_settings.py`](../../../internal/bot/models/chat_settings.py), class `ChatSettingsKey` (~line 255).

`ChatSettingsKey` is a `StrEnum` whose string values are **kebab-case** and match the TOML key name:

```python
class ChatSettingsKey(StrEnum):
    # ...
    MY_NEW_SETTING = "my-new-setting"
    """Short description for code readers."""
```

Convention: `UPPER_CASE` Python name ↔ `kebab-case` string value. Keep them in the same section as related keys (group prompts together, models together, flags together) — the file is organized by category.

## Site 2 — Add the `_chatSettingsInfo` entry

Same file, dict `_chatSettingsInfo` (~line 559). The value is a **TypedDict** (`ChatSettingsInfoValue`) — use dict-literal syntax, not a dataclass call:

```python
_chatSettingsInfo: Dict[ChatSettingsKey, ChatSettingsInfoValue] = {
    # ... existing entries ...
    ChatSettingsKey.MY_NEW_SETTING: {
        "type": ChatSettingsType.STRING,         # or MODEL, BOOL, INT, FLOAT, IMAGE_MODEL
        "short": "Короткое описание на русском",  # shown in /settings list
        "long": "Подробное описание на русском", # shown when editing the setting
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
}
```

> Note: any doc example using `ChatSettingInfo(type=..., short=..., long=..., page=...)` constructor syntax is stale — the type is `ChatSettingsInfoValue` (a `TypedDict`), so entries are dict literals.

### Picking `type`

| `ChatSettingsType` | Use for |
|---|---|
| `STRING` | Prompts, templates, free-form text |
| `BOOL` | On/off flags |
| `INT` | Whole-number thresholds |
| `FLOAT` | Probabilities, ratios, decimal thresholds |
| `MODEL` | LLM model selection (text/chat/summary/condense models) |
| `IMAGE_MODEL` | Image-generation model selection |

### Picking `page`

Controls which `/settings` page surfaces the setting, and implicitly the minimum chat tier that can edit it:

| `ChatSettingsPage` | Intent |
|---|---|
| `STANDART` *(sic)* | Basic, any tier |
| `EXTENDED` | Power-user settings |
| `SPAM` | Spam/moderation |
| `LLM_BASE` | Core LLM config (free tier) |
| `LLM_PAID` | LLM fallbacks / premium |
| `PAID` | Paid features |
| `FRIEND` | Friend-tier features |
| `BOT_OWNER` | Owner-only |
| `BOT_OWNER_SYSTEM` | System internals — "do not modify unless necessary" |

Don't fix the `STANDART` spelling — it's baked into the codebase.

## Site 3 — Add the default value in the right TOML file

Defaults live under [`configs/00-defaults/`](../../../configs/00-defaults/). Most chat-setting defaults go in [`configs/00-defaults/bot-defaults.toml`](../../../configs/00-defaults/bot-defaults.toml) under `[bot.defaults]`:

```toml
[bot.defaults]
# ... existing ...

my-new-setting = "default value"

# or a multi-line prompt:
my-other-prompt = """
Multi-line prompt text.
Use {placeholderName} if the consumer renders the string with format(...).
"""
```

Rules:

- The TOML key is the **kebab-case string** from the `StrEnum` value — i.e. `my-new-setting`, not `MY_NEW_SETTING`, not `my_new_setting`.
- Use triple-quoted strings for multi-line content.
- Use `{placeholder}` format for runtime-substituted values if the consumer does Python-style formatting.
- Never commit secrets. If the default must reference a credential, use `${ENV_VAR}` substitution and keep the actual value in the relevant `.env*`.

Without a default, `/settings` will show the setting but it will be empty, and the consuming code will likely crash or silently no-op.

## Site 4 — Consume the setting correctly

Two gotchas live here. Both are in [`AGENTS.md`](../../../AGENTS.md) and [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §3.

### Gotcha A — `getChatSettings()` returns tuples, not bare values

```python
settings: ChatSettingsDict = await self.db.getChatSettings(chatId)
# settings[key] is a tuple: (value, updatedBy)
rawValue = settings[ChatSettingsKey.MY_NEW_SETTING][0]  # [0] for the value
```

Indexing `[0]` is mandatory. `[1]` is the user ID who set it (useful for audit displays).

### Gotcha B — `setChatSetting()` requires keyword-only `updatedBy`

```python
await self.db.setChatSetting(
    chatId,
    ChatSettingsKey.MY_NEW_SETTING,
    "new value",
    updatedBy=userId,   # keyword-only, REQUIRED
)
```

Omitting `updatedBy` will raise `TypeError`.

## Step 5 — Verify manually

After plumbing all four sites, run the bot locally (or use a test) and:

1. Issue `/settings` in a chat — the new setting should appear on the page you chose.
2. Issue `/settings <my-new-setting>` — you should see the short/long descriptions and the **default value already populated** (not empty).
3. Exercise the consuming code path — it should see the default.
4. Set a non-default value and re-exercise; the override should take effect.

If any of these misbehave, you missed a site.

## Step 6 — Tests

- If the consumer is a handler, its tests should cover both the default-value path and the overridden-value path. Use `tests/conftest.py` fixtures (`testDatabase`, `mockConfigManager`) rather than mocking the DB by hand.
- If the setting has non-trivial parsing/validation logic, add a focused unit test for that logic.

## Step 7 — Documentation

- `docs/llm/configuration.md` — if the new setting introduces a category or pattern worth documenting, add it. For a single routine setting, the file-level `_chatSettingsInfo` docstring and the TOML default often suffice.
- `docs/llm/tasks.md` §4.1 — keep the example reference list current if your setting illustrates a new category.
- `docs/developer-guide.md` — only if it has a section describing the setting area you touched.

Load `update-project-docs` for the full matrix.

## Step 8 — Quality gates

Load `run-quality-gates`. Short form:

```bash
make format lint
make test
```

## Checklist

- [ ] `ChatSettingsKey.MY_NEW_SETTING = "my-new-setting"` (UPPER_CASE enum name ↔ kebab-case string).
- [ ] Enum value has a `"""short docstring"""` underneath it.
- [ ] `_chatSettingsInfo` entry added as a **dict literal** (not a dataclass call) with `type` / `short` / `long` / `page`.
- [ ] Appropriate `ChatSettingsType` and `ChatSettingsPage` chosen.
- [ ] Default value in the matching section of `configs/00-defaults/bot-defaults.toml` (or the relevant defaults TOML), keyed in kebab-case.
- [ ] Consumer code reads `settings[key][0]` (not `settings[key]`) and passes `updatedBy=` when writing.
- [ ] `/settings <my-new-setting>` shows both descriptions and a non-empty default.
- [ ] Tests cover default and override paths.
- [ ] `make format lint && make test` green.
