# `input_image_format` — per-model input-image format conversion

Status: **implemented** — feature shipped; this doc is the retained design reference.
Scope: OpenAI-compatible providers only; add an optional per-model `input_image_format` config key and convert input images into a supported format at model serialization time.

---

## 1. Problem

Yandex AI Studio's `yc/qwen3.6-35b-a3b` model does not accept input images in `image/webp` format (e.g. Telegram stickers download as webp). The model rejects the request. More generally, different vision-capable models accept different image formats, and the bot currently has no way to declare or honor per-model format constraints.

Today, `ModelImageMessage.toDict()` (in `lib/ai/models.py`) builds a `data:{mimeType};base64,...` content block using whatever MIME `magic.from_buffer` detects from the raw bytes — no allowlist, no conversion. A literal TODO in that method (`# TODO: YC AI does not support webp, think about converting it into PNG of JPEG`) and `TODO.md` both track this.

---

## 2. Architecture context — how images reach a model today

- Normal chat never sees image bytes: a background vision call produces a TEXT description stored in the DB; only that text reaches the chat model.
- Base64 image bytes reach a model via exactly ONE construction site: `ModelImageMessage.toDict()`, which reads `self.image` (a `bytearray`) — the only place `self.image` is read in the codebase.
- `ModelImageMessage` is built at two production sites:
  - `_processMediaV2` in `internal/bot/common/handlers/base.py` (background image-description generation).
  - The `/analyze` command in `internal/bot/common/handlers/media.py`.
  - Both call `llmService.generateText(..., modelKey=IMAGE_PARSING_MODEL, fallbackKey=IMAGE_PARSING_FALLBACK_MODEL)`.
- Models are configured declaratively in TOML (`configs/00-defaults/*-models.toml`); the entire model table is passed as `extraConfig` and stored on `AbstractModel._config`. So a new config key needs NO plumbing — it is reachable as `self._config["input_image_format"]`.
- `qwen3.6-35b-a3b` is `provider = "yc-openai"` → goes through `BasicOpenAIModel._generateText`, which serializes messages via `message.toDict(...)`. `YcOpenaiModel` inherits this unchanged.

---

## 3. Key design insight — conversion belongs at the MODEL layer, not the handler layer

Because `generateText` resolves PRIMARY then FALLBACK on the SAME message list, and the handler does not know which model will ultimately run, conversion CANNOT live in the handler — it would need to intersect both models' supported formats, which it cannot cleanly know.

Each model must enforce its OWN `input_image_format` at serialization time. As long as `toDict()` converts from the original `self.image` into a LOCAL variable (never mutates `self.image`), primary and fallback each independently re-derive from the original bytes.

---

## 4. Design

### 4.1 Config (per-model TOML)

Add an OPTIONAL `input_image_format` key to model tables. Value = array of full MIME strings.

Example for the motivating model (`configs/00-defaults/yc-openai-models.toml`, table `[models.models."yc/qwen3.6-35b-a3b"]`):

```toml
input_image_format = ["image/jpeg", "image/png"]
```

Semantics:

- **UNSET or empty** → the model accepts ANY image format (or does not consume images at all). Passthrough, no conversion.
- **SET** → if the detected image MIME is NOT in the list, convert the image to the FIRST format in the list (`supportedFormats[0]`). If the detected MIME IS already in the list, no conversion.

MIME style: FULL MIME strings (`image/jpeg`, `image/png`), matching `magic.from_buffer` output and the data-URL scheme directly — no normalization layer needed.

### 4.2 Conversion helper

A pure function:

```python
def convertImageIfNeeded(
    imageBytes: bytes,
    supportedFormats: list[str] | None,
) -> tuple[bytes, str]:
    """Detect current MIME, convert to a supported format if required.

    Args:
        imageBytes: Raw image bytes (the original, never mutated upstream).
        supportedFormats: Allowed MIME list from the model config, or None/empty.

    Returns:
        A (finalBytes, finalMimeType) pair. On passthrough or conversion
        failure, finalBytes is the original imageBytes unchanged.
    """
```

Logic:

1. Detect current MIME via `magic.from_buffer(imageBytes, mime=True)`.
2. If `supportedFormats` is None/empty OR `currentMime` is in `supportedFormats` → return `(imageBytes, currentMime)` (passthrough).
3. Else `targetMime = supportedFormats[0]`; attempt conversion via Pillow:
   - On success → return `(convertedBytes, targetMime)`.
   - On failure (corrupt image, decode error) → `logger.error(...)` and return `(imageBytes, currentMime)` (graceful degrade; send original and let the API reject).

Implementation notes:

- JPEG does not support alpha channels → flatten to RGB before saving as JPEG via `img.convert("RGB")`.
- MIME→PIL-format map: `image/jpeg`→`JPEG`, `image/png`→`PNG`, `image/webp`→`WEBP`, `image/gif`→`GIF`.

### 4.3 `ModelImageMessage.toDict` integration

`ModelImageMessage.toDict()` gains an optional parameter `supportedImageFormats: Optional[List[str]] = None`. Inside, replace the current `magic.from_buffer` + base64 sequence with a call to `convertImageIfNeeded(bytes(self.image), supportedImageFormats)`, then base64-encode the returned bytes and build the data URL with the returned MIME.

The conversion operates on a LOCAL — `self.image` is NEVER mutated (fallback safety).

The base `ModelMessage.toDict` signature must accept the new kwarg (add `**kwargs` or an explicit defaulted param that it ignores) so the generic provider call `message.toDict("content", supportedImageFormats=...)` works for ALL message types.

### 4.4 Provider threading

`BasicOpenAIModel` (in `lib/ai/providers/basic_openai_provider.py`) reads `inputImageFormats = self._config.get("input_image_format")` and threads it into EVERY `message.toDict(...)` call site — the methods that serialize messages: `_generateText`, `_generateStructured`, `_generateImageViaChatsApi`. Grep `.toDict(` in that file to find all sites.

### 4.5 Scope

OpenAI-compatible providers ONLY (`BasicOpenAIModel` and subclasses: `YcOpenaiModel`, `OpenrouterModel`, custom OpenAI).

The YC SDK provider (`YcAIModel`) is OUT OF SCOPE — it does not handle input images today and `qwen3.6-35b-a3b` is `yc-openai` anyway.

### 4.6 Dependency

Promote `pillow` from a transitive dependency (currently pulled by `python-telegram-bot`, version 12.3.0) to a PINNED DIRECT dependency: add the exact pin to `requirements.direct.txt` under the `# Runtime` section, then regenerate `requirements.txt` via the freeze-requirements command.

Top-level `from PIL import Image` in the conversion helper — hard dependency, no conditional import guard.

---

## 5. Approved decisions (do not change)

1. **Conversion-failure behavior = GRACEFUL**: `logger.error` + keep original bytes. Do NOT raise.
2. **Pillow = HARD pinned direct dependency** (not optional/conditional).
3. **Config MIME style = FULL MIME strings**.
4. **Scope = OpenAI-compatible providers only**.
5. **The adjacent OpenAI-spec bug is a SEPARATE fix, NOT bundled here.** (`ModelImageMessage.toDict` emits `{"type":"text","content":...}` where the spec wants `{"type":"text","text":...}`.)

---

## 6. Out of scope / flagged separately

- The `{"type":"text","content":...}` → `{"type":"text","text":...}` spec key fix (separate change).
- YC SDK provider image support (`YcAIModel._convertMessages` drops images entirely).
- A `support_vision` / input-image capability flag (does not exist today; `support_images` means image GENERATION, not vision input).

---

## 7. Test plan

### 7.1 `convertImageIfNeeded`

- Passthrough when `supportedFormats` unset/empty.
- Passthrough when current MIME is already in the list.
- webp + `["image/jpeg", "image/png"]` → converted to jpeg (bytes change, decode as valid JPEG, MIME = `image/jpeg`).
- webp + `["image/png", "image/jpeg"]` → converted to PNG (first in list).
- Corrupt bytes → graceful degrade (original returned, logged).

### 7.2 `ModelImageMessage.toDict`

- With `supportedImageFormats` on a webp image → data URL carries converted MIME; base64 decodes to a valid image.
- Without `supportedImageFormats` → original MIME in data URL (passthrough).

### 7.3 Fixtures

Generate tiny valid webp/png/jpeg buffers via Pillow in-test, self-contained:

```python
from io import BytesIO
buf = BytesIO()
Image.new("RGB", (2, 2)).save(buf, "WEBP")
webpBytes = buf.getvalue()
```
