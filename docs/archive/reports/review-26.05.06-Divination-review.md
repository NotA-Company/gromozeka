**Created:** 5/6/2026, 10:24:17 AM
**Updated:** 5/6/2026, 10:27:55 AM

Here is the code review for the `master` branch diff:

---

### Summary

Reviewed the new `DivinationHandler` feature branch (~2100 lines of production code, ~2200 lines of tests). The feature adds tarot and runic reading commands, LLM-tool integration, a DB migration, repository, `lib/divination` library, and full test coverage. The structure is solid and idiomatic for this codebase. No critical bugs were found, but there are two important correctness/misconfiguration issues and several minor recommendations.

---

### Critical Issues 🔴

None.

---

### Important Issues 🟡

**[`internal/database/repositories/divinations.py:101`] `drawsJson` list-of-dicts relies on implicit provider-level JSON coercion**

- **Problem**: When a `list[dict]` is passed, the repository never explicitly serializes it to a JSON string. It happens to work on the SQLite path because `convertContainerElementsToSQLite` coerces it — but this is an undocumented implicit contract. A test or future provider that doesn't invoke this coercion will get a raw Python list passed to the DB driver.
- **Suggestion**: Serialize explicitly before handing to the provider:
  ```python
  "drawsJson": drawsJson if isinstance(drawsJson, str) else json.dumps(drawsJson, ensure_ascii=False),
  ```

---

**[`configs/00-defaults/divination.toml:12,15`] `allow-reversed` config keys are defined but never read**

- **Problem**: `DivinationHandler.__init__` reads several config keys but never reads `allow-reversed`. The reversal behavior is hardcoded in `TarotSystem.supportsReversed` and `RunesSystem.supportsReversed`. An operator setting `allow-reversed = false` in config will have zero effect — a silent misconfiguration that also contradicts the documentation.
- **Suggestion**: Either wire up the config key at draw time or remove it from the TOML and docs entirely.

---

**[`internal/bot/common/handlers/divination.py:720–721`] `typingManager.maxTimeout` is permanently mutated, never restored**

- **Problem**: `maxTimeout` is bumped by +300s during image generation but never restored, unlike `originalAction` which is saved and restored. Each invocation permanently grows the timeout.
- **Suggestion**: Save and restore `maxTimeout` symmetrically alongside `originalAction`:
  ```python
  originalTimeout: int = typingManager.maxTimeout
  typingManager.maxTimeout += 300
  # ... image generation ...
  typingManager.maxTimeout = originalTimeout
  ```

---

### Recommendations 🔵

- **[`divination.py:672–686`]** On the `returnToolJson=True` path, an error `sendMessage` fires unconditionally, causing a duplicate/confusing user experience (the user sees a raw error AND the LLM receives a tool error). Gate `sendMessage` on `not returnToolJson`.
- **[`divination.py:750`]** `imgAddPrefix` is fetched from `chatSettings` even when `imageBytes is None`, making it a dead read. Move inside the `if imageBytes is not None:` block.
- **[`lib/divination/base.py:138`]** `_SafeFormatDict.__missing__` silently swallows unknown/misspelled template keys with no warning. Add a `logger.warning(...)` call so operator typos in config templates are surfaced.
- **[`migration_014:44`]** `DEFAULT ''` on `question`/`interpretation` columns is not wrong, but inconsistent with the project pattern of setting all fields explicitly at the application level.

---

### Nitpicks ⚪

- `divination.py:47`: Import alias `divinationL18N` is non-standard; consider `divinationLocalization`.
- `divination.py:629`: Debug log prints `repr` of a tuple of `DrawnSymbol` objects; logging `len(draws)` would be more useful.
- `chat_settings.py:271`: `TAROT_SYSTEM_PROMPT = "taro-system-prompt"` — enum name says `TAROT`, key string says `taro`. Not a bug but confusing.
- `divination.py:824–849`: `_llmGetUnknownLayoutShape` is a dead stub that always returns `None`. Delete or mark with `# TODO:`.

---

### Strengths ✅

- **Import boundary test** (`test_imports.py`) correctly uses subprocess isolation to catch accidental `internal/` leakage from `lib/divination` — the right pattern for this.
- **`_safeFormat` / `_SafeFormatDict`** is a solid defensive design for operator-configured prompt templates that may have optional placeholders.
- **DB persistence is genuinely best-effort**: the `try/except` around `insertReading` prevents DB failures from surfacing to users, with proper two-layer logging for diagnostics.

---

