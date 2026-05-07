# Divination Handler — Tarot & Runes Spreads (Plan)

> **Status:** proposal, not yet implemented
> **Owner:** TBD
> **Scope:** new feature — single bot handler covering tarot and runes readings, plus
> a reusable `lib/divination` library so we can grow into other systems later
> (I-Ching, Lenormand, Geomancy, etc.).

---

## 1. Goal

Add a divination feature exposed in two ways:

1. **Slash commands** for users:
   - `/taro <layout> <question>` — tarot reading
   - `/runes <layout> <question>` — runic reading
2. **LLM tools** so the model can decide on its own to "throw the cards/runes"
   when the user asks naturally (`do_tarot_reading`, `do_runes_reading`).

For each reading the bot must:

1. Resolve the layout (predefined → known shape; unknown → ask LLM later, stub for now).
2. Draw the required number of unique symbols, with reversal flags where applicable.
3. Build an interpretation prompt (system prompt from chat settings + user question +
   user metadata + drawn symbols) and call the LLM.
4. Optionally generate an illustration of the spread (configurable on/off).
5. Send the picture (if generated) plus the interpretation text to the user.
6. Store the reading in DB for later use (no `/lastreadings` command in v1).

---

## 2. Non-Goals (v1)

- No structured (JSON) LLM output — `lib/ai` doesn't support it yet. We add **stubs**
  (`_llmGetUnknownLayoutShape()`) so the integration point exists, but the unknown-layout
  path returns "not supported yet, please use a predefined layout" until structured
  output is added project-wide.
- No `/lastreadings` or any user-facing read-back of stored readings.
- No additional decks beyond Rider–Waite–Smith for tarot.
- No voice / sticker / GIF output.
- No multi-turn dialog ("draw one more card") in v1.

---

## 3. High-Level Architecture

```
+--------------------------------------+        +------------------------------+
| internal/bot/common/handlers/        |        | lib/divination/              |
|   divination.py                      |  uses  |                              |
|                                      | -----> |  base.py     (ABC)           |
|   class DivinationHandler            |        |  tarot.py    (TarotSystem)   |
|     - /taro, /runes commands         |        |  runes.py    (RunesSystem)   |
|     - registers 2 LLM tools          |        |  layouts.py  (Layout, presets)|
|     - shared engine: parse → draw →  |        |  drawing.py  (random.sample) |
|       interpret → image → send       |        |  decks/      (static data)   |
|     - persists each reading via DB   |        |  localization.py (en→ru map) |
+--------------------------------------+        +------------------------------+
                          |
                          v
+--------------------------------------------------------------------+
| internal/services/llm    LLMService.generateText / generateImage   |
|                          (called ONLY from the handler)            |
| lib/ai                   AbstractModel, ModelMessage, …            |
|                          (the only AI dep used by lib/divination)  |
| internal/database        new repo: divinationsRepo                 |
| internal/services/cache  unchanged                                 |
| lib/aurumentation        used by tests (golden replay)             |
+--------------------------------------------------------------------+
```

**Why a separate `lib/divination`?**

- Pure logic, no bot/Telegram/Max coupling.
- Easy unit testing of decks, layouts, drawing — no fixtures, no DB.
- Polymorphism: adding a new system (e.g. I-Ching) = subclassing `BaseDivinationSystem`,
  registering it in the handler. No changes to bot code.
- Matches existing project pattern (compare with `lib/openweathermap`, `lib/yandex_search`).

**`lib/divination` AI boundary:** `lib/divination` may import only from
`lib/ai` (types like `ModelMessage`). It MUST NOT import from
`internal/services/llm`. The handler is the only place that calls
`LLMService.generateText` / `generateImage`; `lib/divination` produces the
input messages and consumes the result text. This keeps the library reusable
outside the bot and matches how other `lib/*` packages stay decoupled.

---

## 4. `lib/divination` — Module Layout

```
lib/divination/
├── __init__.py                  # public re-exports
├── base.py                      # BaseDivinationSystem, Symbol, DrawnSymbol, Reading
├── layouts.py                   # Layout dataclass + LayoutRegistry
├── drawing.py                   # drawSymbols(...) — wraps random.sample, single RNG entry point
├── localization.py              # symbol/layout/position name translations (en → {ru: …})
├── tarot.py                     # TarotSystem(BaseDivinationSystem)
├── runes.py                     # RunesSystem(BaseDivinationSystem)
├── decks/
│   ├── __init__.py
│   ├── tarot_rws.py             # 78-card Rider–Waite–Smith deck (English source-of-truth)
│   └── runes_elder_futhark.py   # 24 Elder Futhark runes
├── test_drawing.py              # unit tests (collocated, picked up by pytest)
├── test_layouts.py
├── test_localization.py
├── test_tarot.py
└── test_runes.py
```

> No `prompts.py` — interpretation and image-generation prompt
> templates live in **chat settings**, with hardcoded fallback defaults
> shipped via `configs/00-defaults/` (see §6). `lib/divination` only knows
> how to **fill in** a template (replace `{userName}`, `{question}`,
> `{cards}`, etc.); it never owns prompt copy.

### 4.1 Core Types (`base.py`)

English is the **source of truth** for every name (symbol, layout, position).
Translations live in `lib/divination/localization.py` as plain dicts keyed by
the English string. A tiny helper (`tr(en, lang)`) returns the localised
string when present, falling back to the English original.

```python
@dataclass(frozen=True)
class Symbol:
    """A single symbol in a deck (tarot card or rune).

    Attributes:
        id: Stable machine ID (e.g. "major_00_fool", "rune_fehu").
        name: English name (source of truth, e.g. "The Fool", "Fehu").
              Localised forms come from lib.divination.localization.
        meaningUpright: Short English upright meaning, used in the interpretation
              prompt as a hint (the LLM does the actual interpretation in the
              user's language).
        meaningReversed: Short English reversed meaning (None if reversals disabled).
        imagePromptFragment: English visual description for image generation.
        metadata: Free-form extra fields (suit, number, aett, element, ...).
    """
    id: str
    name: str
    meaningUpright: str
    meaningReversed: Optional[str]
    imagePromptFragment: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DrawnSymbol:
    """A single draw result.

    Attributes:
        symbol: The Symbol that was drawn.
        reversed: True if drawn in reversed orientation (False for runes by default).
        position: English layout position name (e.g. "Past", "Present", "Future").
        positionIndex: Zero-based index inside the layout.
    """
    symbol: Symbol
    reversed: bool
    position: str
    positionIndex: int


@dataclass(frozen=True)
class Reading:
    """A complete reading result.

    Attributes:
        systemId: "tarot" | "runes" | ...
        deckId: Identifier of the deck used (e.g. "rws", "elder_futhark").
        layout: The Layout used.
        draws: Tuple of DrawnSymbol, length == layout.numSymbols.
        question: User's question (may be empty).
        seed: Optional RNG seed for reproducibility (stored in DB).
    """
    systemId: str
    deckId: str
    layout: "Layout"
    draws: Tuple[DrawnSymbol, ...]
    question: str
    seed: Optional[int]


class BaseDivinationSystem(abc.ABC):
    """Abstract base for divination systems (tarot, runes, ...).

    Note: this class lives in lib/divination and depends only on lib/ai
    (for ModelMessage). It MUST NOT import from internal/.
    """

    systemId: ClassVar[str]                # "tarot", "runes", ...
    deckId: ClassVar[str]                  # "rws", "elder_futhark", ...
    supportsReversed: ClassVar[bool]       # tarot True, runes False
    deck: ClassVar[Tuple[Symbol, ...]]     # full deck

    @classmethod
    def availableLayouts(cls) -> Sequence["Layout"]: ...

    @classmethod
    def resolveLayout(cls, name: str) -> Optional["Layout"]:
        """Case/dash/underscore-insensitive lookup of a predefined layout."""

    @classmethod
    def draw(cls, layout: "Layout", *, rng: Optional[random.Random] = None) -> Tuple[DrawnSymbol, ...]:
        """Delegates to lib.divination.drawing.drawSymbols(...)."""

    @classmethod
    def buildInterpretationMessages(
        cls,
        reading: Reading,
        *,
        userName: str,
        systemPromptTemplate: str,
        userPromptTemplate: str,
        lang: str = "ru",
    ) -> List[ModelMessage]:
        """Build LLM messages: system prompt + user-message rendered from
        userPromptTemplate (with placeholders for userName, question, cards,
        positions, …). Symbol/position names are localised via
        lib.divination.localization.tr(name, lang).
        """

    @classmethod
    def buildImagePrompt(cls, reading: Reading, *, imagePromptTemplate: str) -> str:
        """Render a single image-generation prompt for the whole spread from
        an externally-provided template. Symbol names are emitted in English
        (image models behave better in English)."""
```

### 4.2 Layouts (`layouts.py`)

```python
@dataclass(frozen=True)
class Layout:
    """A divination layout / spread.

    Attributes:
        id: Machine ID (e.g. "celtic_cross").
        nameEn / nameRu: Human-readable names.
        positions: Ordered tuple of position names (length == numSymbols).
        aliases: Tuple of accepted user-facing aliases (case-insensitive).
        systemId: Which system this layout belongs to ("tarot" / "runes" / "*").
    """
    id: str
    nameEn: str
    nameRu: str
    positions: Tuple[str, ...]
    aliases: Tuple[str, ...]
    systemId: str

    @property
    def numSymbols(self) -> int: return len(self.positions)
```

**Predefined layouts (v1):**

| systemId | id              | numSymbols | aliases (subset) |
|----------|-----------------|------------|------------------|
| tarot    | one_card        | 1          | `1`, `1card`, `одна`, `карта` |
| tarot    | three_card      | 3          | `3`, `3card`, `три`, `прошлое-настоящее-будущее` |
| tarot    | celtic_cross    | 10         | `10`, `celtic`, `celtic-cross`, `keltic-cross`, `кельтский-крест`, `крест` |
| tarot    | relationship    | 5          | `5`, `отношения`, `relationship` |
| tarot    | yes_no          | 1          | `yesno`, `да-нет`, `yn` |
| runes    | one_rune        | 1          | `1`, `одна`, `руна` |
| runes    | three_runes     | 3          | `3`, `norns`, `нормы`, `три-руны` |
| runes    | five_runes      | 5          | `5`, `cross`, `пятирунный-крест` |
| runes    | nine_runes      | 9          | `9`, `grid`, `девять` |

Layout name parsing normalises to lowercase, replaces `_`/`-`/spaces with a single
separator, and matches against `aliases ∪ {id}` of all layouts of the active system.

### 4.3 Drawing (`drawing.py`)

The drawing logic is isolated in **one function** so we can swap the
algorithm later without touching the systems:

```python
def drawSymbols(
    deck: Sequence[Symbol],
    layout: Layout,
    *,
    supportsReversed: bool,
    rng: Optional[random.Random] = None,
) -> Tuple[DrawnSymbol, ...]:
    """Draw `layout.numSymbols` unique symbols and assign positions.

    Implementation:
      1. drawnSymbols = (rng or random.SystemRandom()).sample(list(deck), k=layout.numSymbols)
      2. For each (i, sym) in enumerate(drawnSymbols):
           - reversed_ = supportsReversed and rng.random() < 0.5
           - yield DrawnSymbol(sym, reversed_, layout.positions[i], i)

    `random.sample` already guarantees uniqueness without replacement, which
    is exactly what we want for tarot/runes. RNG defaults to
    `random.SystemRandom()`. Tests inject a seeded `random.Random(seed)` for
    determinism.

    Args:
        deck: Source deck (any Sequence).
        layout: Layout describing how many symbols to draw and their positions.
        supportsReversed: When True, each draw has a 50% chance of being reversed.
        rng: Optional injected RNG. Production uses SystemRandom; tests pin a seed.

    Returns:
        Tuple of DrawnSymbol with length == layout.numSymbols.
    """
```

> Single function, single RNG entry point — swapping the algorithm later
> (e.g. for ritualistic shuffle-then-pop, weighted draws, or external
> entropy) is a one-line change here.

### 4.4 Decks & Localization

**English is the source of truth.** Each `Symbol` carries only an English
`name`, `meaningUpright`, `meaningReversed`, and `imagePromptFragment`.
Translations are pulled from `lib/divination/localization.py`.

- **`decks/tarot_rws.py`** — 78 `Symbol` objects: 22 Major Arcana + 4 suits × 14
  Minor Arcana. Each carries English name, short upright + reversed meaning,
  and a one-sentence visual fragment for image-prompt assembly.
- **`decks/runes_elder_futhark.py`** — 24 `Symbol` objects (Fehu … Dagaz),
  with `meaningReversed=None`. Three aetts in metadata.

Static Python literals — no I/O, easy diff. If they grow too large for review
comfort, we split each suit / aett into its own file but stay in code (no JSON).

#### `localization.py`

```python
# Each top-level dict is keyed by English string (Symbol.name, Layout position,
# layout English name). Values are dicts {langCode: localised}.
# Only "ru" is filled in v1; missing languages fall back to the English original.

SYMBOL_NAMES: Dict[str, Dict[str, str]] = {
    "The Fool":      {"ru": "Шут"},
    "The Magician":  {"ru": "Маг"},
    # … 78 tarot + 24 runes
    "Fehu":          {"ru": "Феху"},
    # …
}

POSITION_NAMES: Dict[str, Dict[str, str]] = {
    "Past":     {"ru": "Прошлое"},
    "Present":  {"ru": "Настоящее"},
    "Future":   {"ru": "Будущее"},
    # … all positions used by predefined layouts
}

LAYOUT_NAMES: Dict[str, Dict[str, str]] = {
    "Three-Card Spread":   {"ru": "Расклад на три карты"},
    "Celtic Cross":        {"ru": "Кельтский крест"},
    # …
}


def tr(table: Mapping[str, Mapping[str, str]], enKey: str, lang: str) -> str:
    """Translate `enKey` to `lang` using `table`. Falls back to enKey if missing."""
```

> Adding a new language is data-only: extend the existing dicts. Adding a
> new symbol/layout/position requires both the English source-of-truth (in
> the deck or layout file) **and** an entry in the appropriate localization
> dict (a unit test enforces this — see §10.1).

---

## 5. `internal/bot/common/handlers/divination.py`

Single handler, ~400 lines target:

```python
class DivinationHandler(BaseBotHandler):
    """Tarot & runes readings handler

    Registers /taro and /runes commands and two LLM tools.
    Lookups divination systems by name and delegates to lib/divination
    for all deck / layout / drawing / prompt-building logic.

    Attributes:
        llmService: LLMService singleton, for generateText / generateImage / registerTool.
        systems: Mapping of systemId -> BaseDivinationSystem subclass.
        config: Resolved divination config from ConfigManager.
    """
```

### 5.1 Init

- Read config via `configManager.get("divination", {})`.
- Raise `RuntimeError("...")` if `enabled` is False (pattern matches `WeatherHandler`)
  — handler will only be constructed when `HandlersManager` sees the flag.
- Register systems: `{"tarot": TarotSystem, "runes": RunesSystem}` (extensible).
- Register LLM tools (see §7) — only if `tools-enabled = true` in config.

### 5.2 Command flow (shared between `/taro` and `/runes`)

```
1. Parse args:
     - First whitespace-delimited token = layout name.
     - Rest of the line = user question (may be empty).
   On missing/invalid input: send help message, set MessageCategory.BOT_ERROR.

2. systemCls = self.systems[commandName]   # taro -> tarot, runes -> runes

3. layout = systemCls.resolveLayout(layoutName)
   if layout is None:
        # Stub: structured-output not supported yet.
         sendMessage("Layout '<name>' is not yet supported. "
                     "Predefined layouts: <list>.")
        return
   # NOTE: future hook is `_llmGetUnknownLayoutShape(systemCls, layoutName)`,
   # which will be implemented when lib/ai gets structured output.

4. await self.llmService.rateLimit(chatId, chatSettings)

5. Within `startTyping()`:
     a. reading = systemCls.draw(layout)               # uses lib/divination/drawing
     b. systemPrompt   = chatSettings[<TAROT|RUNES>_SYSTEM_PROMPT].toStr()
        userTemplate   = chatSettings[DIVINATION_USER_PROMPT_TEMPLATE].toStr()
        messages = systemCls.buildInterpretationMessages(
            reading,
            userName=ensuredMessage.sender.displayName,
            systemPromptTemplate=systemPrompt,
            userPromptTemplate=userTemplate,
            lang="ru",   # localised symbol/position names; question itself drives reply language
        )
     c. llmRet = await llmService.generateText(
            messages, chatId=chatId, chatSettings=chatSettings,
            llmManager=self.llmManager,
            modelKey=ChatSettingsKey.CHAT_MODEL,
            fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
        )
        if llmRet.status != FINAL: sendErrorMessage; return.
     d. interpretationText = llmRet.resultText.

6. Image step (if config["image-generation"] is True):
     - typingManager.action = UPLOAD_PHOTO; sendTypingAction()
     - imageTemplate = chatSettings[DIVINATION_IMAGE_PROMPT_TEMPLATE].toStr()
     - imagePrompt = systemCls.buildImagePrompt(
           reading, imagePromptTemplate=imageTemplate,
       )
     - imgRet = await llmService.generateImage(imagePrompt, ...)
     - On success: insert into `media_attachments` (file_unique_id =
       generated UUID, media_type='photo', status='processed', prompt=imagePrompt),
       remember the file_unique_id for the divinations row, then
       sendMessage(photoData=imgRet.mediaData,
                   messageText=interpretationText[:CAPTION_LIMIT],
                   mediaPrompt=imagePrompt, ...)
     - On failure → log + fall through to text-only (mediaId stays None).

7. If no image (disabled or failed):
     - sendMessage(messageText=interpretationText, MessageCategory.BOT_COMMAND_REPLY)
   If interpretationText > caption limit (1024): send photo+caption, then a
   follow-up text message with the rest.

8. Persist reading to DB (see §8). Failure here is logged but does NOT fail the user reply.
```

### 5.3 Public method shape

`CommandCategory.AI` does **not** exist in the codebase — we use
`CommandCategory.TOOLS` (same as `WeatherHandler` / `MediaHandler`).

The help message is **assembled dynamically** at handler-construction time
from the registered system's `availableLayouts()` so adding a new layout
automatically extends `/help` output. We build it once in `__init__` and
embed it via the decorator (decorator arguments are evaluated at class-body
time, so we set the `helpMessage` on each command from a module-level
function that reads the layout registry).

```python
def _buildTaroHelp() -> str:
    layoutsList = ", ".join(f"`{lay.id}`" for lay in TarotSystem.availableLayouts())
    return (
        " `<layout>` `[question]`: Раскинуть карты Таро.\n"
        f"Доступные расклады: {layoutsList}.\n"
        "Если расклад не указан — используется `three_card`."
    )


def _buildRunesHelp() -> str:
    layoutsList = ", ".join(f"`{lay.id}`" for lay in RunesSystem.availableLayouts())
    return (
        " `<layout>` `[question]`: Раскинуть руны.\n"
        f"Доступные расклады: {layoutsList}.\n"
        "Если расклад не указан — используется `three_runes`."
    )


@commandHandlerV2(
    commands=("taro", "tarot", "таро"),
    shortDescription="<layout> [question] - Раскинуть карты Таро",
    helpMessage=_buildTaroHelp(),
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def taroCommand(self, ensuredMessage, command, args, updateObj, typingManager) -> None: ...

@commandHandlerV2(
    commands=("runes", "rune", "руны"),
    shortDescription="<layout> [question] - Раскинуть руны",
    helpMessage=_buildRunesHelp(),
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def runesCommand(self, ensuredMessage, command, args, updateObj, typingManager) -> None: ...
```

Both delegate to `_handleReading(systemId, ensuredMessage, args, typingManager)`.

> The error-reply path (unknown layout, empty input) ALSO emits the same
> "Доступные расклады: …" list so users discover valid names without reaching
> for `/help`.

### 5.4 Stub for future structured-output use

```python
async def _llmGetUnknownLayoutShape(
    self, systemCls: type[BaseDivinationSystem], layoutName: str
) -> Optional[Layout]:
    """STUB: ask LLM for the shape of an unknown layout (positions + count).

    Not implemented in v1 — `lib/ai` does not yet support structured/JSON output.
    Once it does, this method will:
      1. Send a structured-output prompt requesting
         `{"nCards": int, "positions": list[str]}`.
      2. Validate (1 <= nCards <= 21, len(positions) == nCards).
      3. Cache `(systemId, layoutName)` -> result via CacheService.
      4. Return a synthesised Layout (id="ad_hoc:<slug>", aliases=()).

    Args:
        systemCls: Divination system requesting the layout.
        layoutName: Raw user-supplied name.

    Returns:
        None always (stub).
    """
    logger.info(f"Unknown layout '{layoutName}' for {systemCls.systemId}: "
                "structured output not implemented yet.")
    return None
```

---

## 6. Configuration

The `[divination]` TOML section is **only feature-flag plumbing** — no prompt
text or stylistic hint lives there. Everything tunable per-chat (system
prompts, user-message template, image-prompt template) is a `ChatSettingsKey`,
populated with the project-wide default in `configs/00-defaults/`.

```toml
# configs/00-defaults/divination.toml  (or appended to an existing defaults file)
[divination]
enabled = false                 # gated, default off; per-deployment override
tarot-enabled = true
runes-enabled = true
image-generation = true         # set false to skip image step entirely
tools-enabled = true            # register LLM tools for natural-language calls

# Per-system declarative bits — future-proofing.
[divination.tarot]
allow-reversed = true

[divination.runes]
allow-reversed = false
```

Conditional registration in `HandlersManager.__init__()` follows the
`WeatherHandler` pattern:

```python
if self.configManager.get("divination", {}).get("enabled", False):
    self.handlers.append(
        (DivinationHandler(configManager, database, llmManager, botProvider),
         HandlerParallelism.PARALLEL),
    )
```

### 6.1 New `ChatSettingsKey` entries

Add to [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py):

| Key (enum)                                | TOML key                          | Type   | Page              | Purpose |
|-------------------------------------------|-----------------------------------|--------|-------------------|---------|
| `TAROT_SYSTEM_PROMPT`                     | `tarot-system-prompt`              | STRING | LLM_BASE          | System prompt for tarot interpretation. |
| `RUNES_SYSTEM_PROMPT`                     | `runes-system-prompt`             | STRING | LLM_BASE          | System prompt for runes interpretation. |
| `DIVINATION_USER_PROMPT_TEMPLATE`         | `divination-user-prompt-template` | STRING | BOT_OWNER_SYSTEM  | User-message template; placeholders: `{userName}`, `{question}`, `{layoutName}`, `{cardsBlock}`, `{positionsBlock}`. Same template for tarot & runes. |
| `DIVINATION_IMAGE_PROMPT_TEMPLATE`        | `divination-image-prompt-template`| STRING | BOT_OWNER_SYSTEM  | Image-generation prompt template; placeholders: `{layoutName}`, `{spreadDescription}`, `{styleHint}`. |

The handler reads each setting via `chatSettings[ChatSettingsKey.X].toStr()`,
identical to `CHAT_PROMPT` / `SUMMARY_PROMPT`. If the chat hasn't customised
it, the value comes from the default loaded by `configs/00-defaults/`.

### 6.2 Default prompt values

Defaults are shipped in **`configs/00-defaults/`**, not in Python code, so an
operator can edit them without re-deploying. They live under
`[bot.defaults]` (the same place existing `*-prompt` defaults live for
`SUMMARY_PROMPT`, `CHAT_PROMPT`, etc.). Sketch:

```toml
[bot.defaults]
# Existing keys: chat-prompt = "...", summary-prompt = "...", …

tarot-system-prompt = """
Ты — опытный таролог. Тебе дают расклад карт Таро Райдера-Уэйта (Rider-Waite-Smith) и вопрос пользователя.
Дай содержательную, доброжелательную интерпретацию. Учитывай позицию каждой карты в раскладе и её ориентацию (прямая / перевёрнутая).
Отвечай на том же языке, на котором задан вопрос пользователя. Если язык вопроса неясен — отвечай по-русски.
"""

runes-system-prompt = """
Ты — опытный рунолог традиции Старшего Футарка. Тебе дают рунический расклад и вопрос пользователя.
Дай содержательную, доброжелательную интерпретацию каждой руны в её позиции; перевёрнутые значения не используются.
Отвечай на том же языке, на котором задан вопрос пользователя. Если язык вопроса неясен — отвечай по-русски.
"""

divination-user-prompt-template = """
Имя пользователя: {userName}
Вопрос: {question}

Расклад: {layoutName}
Позиции: {positionsBlock}

Выпавшие символы:
{cardsBlock}

Дай интерпретацию для пользователя.
"""

divination-image-prompt-template = """
Render the {layoutName} divination spread as a single illustration.
Spread layout and drawn symbols (in English):
{spreadDescription}

Style: {styleHint}
"""
```

The default `{styleHint}` value used when rendering the image template lives
*inside* the template itself (operators just edit the string) — it is not a
separate key. Example default style hint phrase shipped in the template:
*"vintage occult illustration, warm parchment background, ornate borders"*.

### 6.3 No `chatLanguage` available

Per spec: language is **inferred from the user's question**. The default
system prompts above explicitly instruct the model to do so.

---

## 7. LLM Tools (Step 2)

Two tools registered with `LLMService` (gated on `divination.tools-enabled`):

### 7.1 `do_tarot_reading`

```python
LLMFunctionParameter(name="question", type=STRING, required=True,
    description="The user's question to interpret with the tarot reading."),
LLMFunctionParameter(name="layout",   type=STRING, required=False,
    description="Layout name. One of: one_card, three_card, celtic_cross, "
                "relationship, yes_no. Default: three_card."),
LLMFunctionParameter(name="generate_image", type=BOOLEAN, required=False,
    description="Whether to also generate a spread image. Default: false."),
```

Behaviour:

- Resolves `extraData` to retrieve `ensuredMessage` + `typingManager`
  (same pattern as `MediaHandler._llmToolGenerateAndSendImage`).
- Runs the same engine as the slash command.
- **Defaults to text-only** when invoked via tool-call (saves quota); the LLM
  can opt in to images via `generate_image=true`.
- Returns `utils.jsonDumps({"done": True, "summary": "Drew 3 cards: ..."})` so
  the host LLM can incorporate the reading naturally.

### 7.2 `do_runes_reading`

Symmetrical to the tarot tool with `layout` enum
`one_rune | three_runes | five_runes | nine_runes`, default `three_runes`.

### 7.3 No structured output yet

Both tools accept only the predefined layouts. Unknown layouts → tool returns
`{"done": false, "errorMessage": "Unknown layout '<x>'. Use one of: ..."}`
so the LLM can self-correct. The structured-output stub stays in place.

---

## 8. Persistence

New table `divinations`, added in **migration 014**.

The primary key is the **composite `(chat_id, message_id)`** — the originating
`/taro` or `/runes` message uniquely identifies the reading. This matches the
`chat_messages` table's PK convention (see migration 013) and complies with
the project's "no `AUTOINCREMENT`, no `SERIAL`" rule from `AGENTS.md` (SQL
portability across SQLite / PostgreSQL / MySQL).

The image is **not stored as bytes here**. Instead it links to
`media_attachments.file_unique_id` — same pattern as
`chat_messages.media_id`. `StorageService` and the existing media pipeline
already manage the bytes; the divinations row just holds the FK.

```sql
CREATE TABLE divinations (
    chat_id         INTEGER NOT NULL,                   -- Originating message's chat_id
    message_id      TEXT    NOT NULL,                   -- Originating message's message_id (MessageIdType, str-typed for cross-platform)
    user_id         INTEGER NOT NULL,                   -- User who requested the reading
    system_id       TEXT    NOT NULL,                   -- 'tarot' | 'runes'
    deck_id         TEXT    NOT NULL,                   -- 'rws' | 'elder_futhark'
    layout_id       TEXT    NOT NULL,                   -- Layout.id
    question        TEXT    NOT NULL DEFAULT '',
    draws_json      TEXT    NOT NULL,                   -- list[{symbolId, reversed, position, positionIndex}]
    interpretation  TEXT    NOT NULL DEFAULT '',
    image_prompt    TEXT,                               -- Final rendered image prompt (NULL if no image step)
    media_id        TEXT,                               -- FK to media_attachments.file_unique_id (NULL if no image / generation failed)
    rng_seed        INTEGER,                            -- Optional reproducibility seed
    invoked_via     TEXT    NOT NULL,                   -- 'command' | 'llm_tool'
    created_at      TIMESTAMP NOT NULL,                 -- Set by app, no DEFAULT (migration 013 rule)
    PRIMARY KEY (chat_id, message_id)
);

CREATE INDEX idx_divinations_user_created ON divinations (chat_id, user_id, created_at);
```

> No FK constraint declared on `media_id` (consistent with how
> `chat_messages.media_id` is currently defined — comment-only "Foreign key
> to …"). The handler is responsible for inserting into
> `media_attachments` first, then writing the divinations row with the
> resulting `file_unique_id`.
>
> Single index is enough for v1; the time-only index was dropped per the
> review — we don't have a use case that scans all divinations across all
> chats.

**Repo class:** `internal/database/repositories/divinations.py`,
`DivinationsRepository` exposing:

- `async insertReading(reading: Reading, *, chatId, messageId, userId, interpretation, imagePrompt, mediaId, invokedVia) -> None`
  — uses `(chat_id, message_id)` as natural PK, no auto-id returned.
- (No retrieval methods in v1 — kept minimal until `/lastreadings` lands.)

Wired into `Database` like other repos.

> Failure to persist must NOT block the user reply. Wrap the DB insert in
> `try/except` + `logger.error`; reading is delivered regardless.

---

## 9. Rate Limiting

Reuse the LLM rate limiter — the standard pattern:

```python
chatSettings = await self.getChatSettings(chatId=chatId)
await self.llmService.rateLimit(chatId, chatSettings)
```

This already covers both `generateText` and `generateImage` calls — one
`rateLimit()` per command invocation is enough (the inner `LLMService` calls
also `rateLimit`, but on the same key, so it's idempotent within a small
window). No new rate-limiter queue.

---

## 10. Testing Strategy

All tests use `./venv/bin/pytest`, no live API calls.

### 10.1 Unit (collocated under `lib/divination/`)

| File | What it covers |
|------|----------------|
| `test_drawing.py`      | `drawSymbols` returns N unique symbols, deterministic with seeded RNG, `reversed` only when `supportsReversed`, statistical sanity check (~50% reversals over 10k draws). |
| `test_layouts.py`      | Alias resolution (case/sep-insensitive), positions length matches numSymbols. |
| `test_localization.py` | Every Symbol.name and Layout position used in v1 has at least an `"ru"` entry; `tr()` falls back to English when key missing; no duplicate localised values within the same dict. |
| `test_tarot.py`        | Deck has 78 unique IDs, all 4 suits × 14 + 22 majors, every card has English name/upright/reversed/imagePromptFragment, `buildInterpretationMessages` and `buildImagePrompt` correctly substitute every placeholder in a template. |
| `test_runes.py`        | Deck has 24 unique IDs, no `meaningReversed`, template rendering correct. |
| `decks/test_decks.py`  | Schema validation: every Symbol field non-empty (except optional ones), no duplicate English names. |

### 10.2 Handler (under `tests/bot/`)

`tests/bot/test_divination_handler.py`:

- Uses `mockBot`, `mockConfigManager`, `testDatabase`, `mockLLMService`
  fixtures from `tests/conftest.py`.
- Mocks `LLMService.generateText` to return a fixed `ModelRunResult`.
- Mocks `LLMService.generateImage` (success and failure paths).
- Asserts:
  - `/taro three_card что меня ждёт` → 3 cards drawn, single `sendMessage` with photo+caption.
  - `/runes nine_runes` (no question) → 9 runes drawn, sane prompt assembled, no image when `image-generation = false`.
  - Unknown layout → "not supported yet" reply, no LLM call.
  - DB row written via the repo.
  - LLM tool registration fires when `tools-enabled = true`, omitted otherwise.

### 10.3 Golden / Aurumentation

For the **prompt-building + LLM round-trip** integration test, use the existing
`lib/aurumentation` framework (mirrors `tests/lib_ai/golden/`):

- Add `tests/divination/golden/` with:
  - `inputs/` — sample reading inputs (system, layout, drawn symbols, question).
  - `outputs/` — recorded LLM responses (text + image bytes hash).
  - `collect.py` — uses `lib.aurumentation.collector.collectGoldenData(...)`
    to record traffic against a real provider once.
  - `test_golden.py` — uses `GoldenDataReplayer` so CI replays deterministically
    without API calls.

This gives us regression coverage on prompt format without burning quota.

### 10.4 Lint / format

Standard project workflow. `lib/divination` is **not** under `lib/ext_modules/`,
so plain `make format lint` will pick it up.

---

## 11. Implementation Order

Suggested sequencing — small, mergeable steps:

1. **`lib/divination` skeleton** — `base.py`, `layouts.py`, `drawing.py`,
   `localization.py`, empty deck stubs. Unit tests for drawing + layout
   resolution + localization fallback. Imports from `lib/ai` only.
2. **Decks** — populate `tarot_rws.py` (chunky but pure data) and
   `runes_elder_futhark.py`. Fill `localization.py` with full Russian
   translations for every Symbol/position used. Deck integrity + localization
   coverage tests.
3. **System classes** — `TarotSystem`, `RunesSystem`. Tests for template
   rendering (placeholder substitution + localised name lookup).
4. **DB migration 014 + `DivinationsRepository`** — composite-PK schema as
   per §8, FK-by-comment to `media_attachments`. Schema test + insert test.
5. **Chat-settings keys + default config** — add the four new
   `ChatSettingsKey` entries, ship default prompt strings under
   `configs/00-defaults/`, sanity-check via
   `./venv/bin/python3 main.py --print-config`.
6. **`DivinationHandler` (commands only)** — `/taro` + `/runes`, no LLM tools,
   no image yet (text-only path). Wire into `HandlersManager` behind config flag.
7. **Image generation** — render image template, call `generateImage`,
   insert `media_attachments` row, send photo. Fall through to text on failure.
8. **LLM tools** — register `do_tarot_reading`, `do_runes_reading`. Test tool
   handlers with mocked `LLMService`.
9. **Persistence wiring** — call `DivinationsRepository.insertReading` from
   handler, log-and-swallow on failure.
10. **Golden tests** — record once, commit fixtures, ensure CI replays.
11. **Docs** — update `docs/llm/handlers.md` (new handler row),
    `docs/llm/configuration.md` (`[divination]` section + new chat-settings
    keys), `docs/database-schema.md` + `docs/database-schema-llm.md`
    (new table). Use the `update-project-docs` skill.

Each step ends with `make format lint && make test` before moving on.

---

## 12. Risks / Open Questions

| Risk | Mitigation |
|------|------------|
| 78-card RWS deck data is bulky and tedious to validate. | Generate from a single source-of-truth dict in code; add a `test_decks.py` that asserts every card has all required fields. |
| Image generation can be slow / fail. | Already handled by `LLMService.generateImage` with fallback. We additionally fall through to text-only on failure rather than reporting an error to the user. |
| Caption length cap (Telegram 1024). | Send photo with truncated caption, follow-up message with full text. Same approach already used in `MediaHandler`. |
| Russian/English prompts may produce mismatched-language replies. | Explicit instruction baked into the default `tarot-system-prompt` / `runes-system-prompt` shipped via `configs/00-defaults/`; an operator can fine-tune per chat without code changes. |
| Persona drift from `CHAT_PROMPT` could confuse the divination "voice". | We use **dedicated** `TAROT_SYSTEM_PROMPT` / `RUNES_SYSTEM_PROMPT` keys, not `CHAT_PROMPT`. |
| `lib/divination` accidentally importing `internal/services/llm` would break the layering. | A `flake8` import-check / pyright run plus a one-liner test (`importlib.import_module('lib.divination'); assert no module under sys.modules starts with 'internal.services.llm'`) keeps the boundary honest. |
| Structured-output stub may stay unimplemented for a long time. | Only known layouts are accepted in v1; users get a clear list of supported names. |
| Reversal probability could be configurable later. | Currently hard-coded 50%. Easy to lift into the layout or system class when needed — `drawSymbols` already takes `supportsReversed` as a parameter, future signature can grow a `reversedProbability=0.5` kwarg. |
| RNG quality: `random.SystemRandom` is OS-backed — should be fine. | Tests pin a `random.Random(seed)`; production uses `SystemRandom`. |

---

## 13. Out of Scope (explicitly)

- I-Ching, Lenormand, Geomancy, runic galdr, oracle decks → future systems
  via `BaseDivinationSystem` subclass.
- Multi-turn dialogues ("draw another card to clarify").
- Sharing readings between users.
- Tarot reversal probability configuration.
- Per-user statistics ("you've drawn The Tower 7 times this month").
- `/lastreadings` / read-back commands.
- Structured LLM output for unknown layouts (stubbed).

---

*Plan author note: assumes single-handler / single-`lib` design as per discussion.
Ready for review.*
