---
category: design
---

> **Partially superseded (2026-10-06).** The attachment mechanism and the image cap were reworked in
> [`native-vision-v2-construction-attach.md`](native-vision-v2-construction-attach.md) (images now attach at
> message-construction time; the `max-images-per-request` cap was removed), and storage placement/key layout moved to
> [`scoped-storage-design-v1.md`](scoped-storage-design-v1.md) (own `[storage.storages.vision]` backend, bare
> `{sha512}.{ext}` keys). The rest of this document remains the ratified v1 record; read the two successors first.

# Native Vision Design v1

**Author:** OpenCode Architect
**Date:** 2026-09-26
**Status:** Ratified 2026-09-26 — pre-implementation. User-approved decisions are marked
**RATIFIED**; deferred work is marked **FOLLOW-UP**. This document records the ratified
design, not the earlier proposal variants it supersedes.

---

## 1. Overview

### 1.1 Goal

Introduce a per-chat Bool chat setting `native-vision` (bot-owner-settable) that sends user
images natively — raw pixels — to vision-capable chat models, instead of relying solely on
text descriptions produced by a separate image-parsing model.

Mental model:

- `parse-attachments` = describe images in words.
- `native-vision` = also show the image itself to the chat model.

The two settings are independent gates over the same receipt flow; neither implies the other.

### 1.2 Motivation

No current feature sends images to the chat model. Chat calls are string-only:
`LLMMessageHandler` → `_sendLLMChatMessage`
([`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):229). An image reaches
the chat LLM only as a textual `mediaDescription` rendered into context — losing layout,
charts, screenshots, memes, and anything the parsing model failed to mention. Meanwhile, all
the machinery for native image input already exists at the `lib/ai` layer and is
production-exercised by two non-chat paths (image parsing and `/analyze`); nothing consumes
it from the chat path. This design wires it in, behind a per-chat owner switch.

### 1.3 Ratified decisions (user, 2026-09-26)

1. **No `keep-descriptions` knob** — `parse-attachments` stays the sole governor of the
   description pipeline.
2. **Attach-always history policy** — attach images whenever stored bytes exist (current
   turn, reply-parent, all history turns), most-recent-N under the request cap; other
   variants (e.g. last-N-turns windows) later.
3. **TTL concept ships from day one** — `ttl-days = 30` default in config; the daily GC cron
   that enforces it is a **FOLLOW-UP**. Iteration 1 ships the minimal base with no GC
   running.
4. **Skip-`_awaitMedia`-wait is a FOLLOW-UP** — iteration 1 keeps the up-to-300 s
   description wait exactly as today.
5. `max-image-dimension` configurable, 2048 default.
6. **Both-models eligibility rule confirmed** — primary AND fallback chat models must declare
   `support_image_input`.
7. `/analyze` integration deferred (follow-up).
8. **Download + normalize at receipt on both platforms, never re-download later** — bytes
   gone → description fallback.
9. **Stickers included** — treated as images throughout the stack.

## 2. Current State (verified against source 2026-09-26)

Capability plumbing (complete, metadata-only today):

- Per-model `support_image_input` flag exists (`lib/ai/abstract.py:829`, exposed via
  `getInfo()`), sourced from model catalogs; its only consumer today is the `/configure`
  picker label (see the vision-flag arc, linked in References). This feature becomes the
  flag's first real request-time consumer.
- `ModelImageMessage.toDict` builds the multipart `image_url` construction
  (`lib/ai/models.py:833-894`); the class holds a single `image: bytearray`
  (`lib/ai/models.py:819-831`).
- Send-time per-model format conversion exists: `convertImageIfNeeded`
  (`lib/ai/models.py:78-151`; Pillow re-encode, JPEG alpha flatten at
  `lib/ai/models.py:140-141`, 50 MP decompression-bomb guard `MAX_VISION_IMAGE_PIXELS` at
  `lib/ai/models.py:75`, never-raises contract), wired via `input_image_format`
  (`lib/ai/providers/basic_openai_provider.py:536-541`). `pillow==12.3.0` is already pinned.

Receipt flow ([`base.py`](../../internal/bot/common/handlers/base.py)):

- `_processMediaV2` (`base.py:1879`) is THE branch point; `mediaData` bytes are still in
  scope there.
- Bytes are downloaded only for save (`base.py:1987-1996`, `save-attachments` gate) or parse
  (`base.py:2046-2051`, `parse-attachments` gate); otherwise they are ephemeral.
- The `needParseImage` gate (`base.py:1998-2001`) engages for `mediaType in (IMAGE, STICKER)`.
- Only the LLM parse task is backgrounded (`base.py:2102-2105`).
- `storeAttachment` (`base.py:2119-2154`) is the sha512 content-dedup store pattern
  (`{prefix}{mediaType}-{sha512}.{ext}` → StorageService).
- MIME is known only post-download via `magic.from_buffer` (`base.py:2062`).
- Some OpenRouter image-PARSING models reject text+image in one message — `_parseImage` sends
  `content=""` (comment at `base.py:2092-2095`).

Storage:

- [`StorageService`](../../internal/services/storage/service.py) with null/fs/s3 backends,
  wired as `self.storage` on every handler. Default backend `type = "null"`
  ([`storage.toml`](../../configs/00-defaults/storage.toml):6). Read-back precedent:
  resender, `storage.get(localUrl)`
  ([`resender.py`](../../internal/bot/common/handlers/resender.py):399-411).
- The team deliberately retired its last DB BLOB store (migration_025). Highest existing
  migration is migration_029 — number 030 is free (verified in
  [`internal/database/migrations/versions/`](../../internal/database/migrations/versions/)).

Context assembly:

- Current message: `LLMMessageHandler` assembly
  ([`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):781-788); history:
  `getThreadByMessageForLLM` (`base.py:786`) → `fromDBChatMessage` → `formatForLLM`
  (mediaDescription JSON key / `<media-description>` tag,
  [`ensured_message.py`](../../internal/bot/models/ensured_message.py):1064-1205).
- One message list is serialized for both the primary and the fallback attempt
  (`llm_messages.py:209-226`).
- Chat-time render blocks up to 300 s on pending descriptions (`_awaitMedia`,
  `MAX_MEDIA_AWAIT_SECS = 300`, `ensured_message.py:52`, reached via `updateMediaContent`
  during `formatForLLM`).
- Albums: Telegram = N messages sharing `media_group_id`, re-expanded at render
  (`ensured_message.py:854-862`); Max = multiple attachments on one message.
- `media_attachments` PK is the stable platform key: `file_unique_id` (Telegram) /
  `image:{photo_id}` (Max). Max `file_id` is a CDN URL with unverified expiry — late
  re-download is not a reliable option.

## 3. Design Decisions

### 3.1 Setting: `ChatSettingsKey.NATIVE_VISION`

- `ChatSettingsKey.NATIVE_VISION = "native-vision"`, `ChatSettingsType.BOOL`, default
  `false`.
- Page: `ChatSettingsPage.BOT_OWNER`. Page placement IS the existing owner-only mechanism:
  `ChatSettingsPage.minTier()` → `ChatTier.BOT_OWNER`
  ([`chat_settings.py`](../../internal/bot/models/chat_settings.py):278-279), and
  `/configure` elevates owners
  ([`configure.py`](../../internal/bot/common/handlers/configure.py):291-292). Sibling
  precedent: `SAVE_ATTACHMENTS` on the same page.
- 4-site wiring per the
  [add-chat-setting recipe](../../.agents/skills/add-chat-setting/SKILL.md):
  enum member + `_chatSettingsInfo` TypedDict entry + default under `[bot.defaults]` in
  [`bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) + consumer code. The
  long description MUST document (a) that enabling stores image bytes on disk for up to
  `ttl-days`, and (b) that the feature engages only when both chat models declare
  `support_image_input`.
- Config-manager trap: any `[bot.defaults]` key not present in `ChatSettingsKey` is silently
  dropped ([`manager.py`](../../internal/config/manager.py):464-487) — all four sites must
  land together.
- **RATIFIED**: independent of `parse-attachments` (parallel gates). **No
  `keep-descriptions` knob** — `parse-attachments` stays the sole governor of the
  description pipeline; there is deliberately nothing to tune about how the two interact.

### 3.2 Image store

Decision: filesystem via existing `StorageService`, plus a metadata column on
`media_attachments`; no DB BLOB table.

- The null/fs/s3 backend abstraction comes free (an S3 upgrade needs no schema change). A DB
  BLOB table was rejected: the team retired its last BLOB store in migration_025, and SQLite
  blob bloat is a known cost.
- Key convention: `vision/{sha512}.{ext}` — content-addressed dedup mirroring the
  `storeAttachment` pattern (`base.py:2119-2154`), with `ext` derived from the
  post-normalization MIME. Do NOT reuse `save-attachments`/`local_url`: different bytes
  (normalized vs original) and different lifecycle — resender must keep serving originals.
- Metadata: migration 030 adds `vision_url TEXT` to `media_attachments` (sketch in §5). A
  real column rather than another `metadata` JSON key, so "has vision bytes" is a cheap
  predicate to query and future GC can clear it with one UPDATE.
- Null storage backend (today's default): fail-soft, three layers —
  1. warn in the `/configure` confirmation when `native-vision` is enabled while the storage
     backend is null;
  2. rate-limited warning (once per chat) in `_processMediaV2` when the store step fails;
  3. chat time silently falls back to descriptions.

  The feature never surfaces an error to end users.
- Lifecycle: **RATIFIED** — the TTL concept ships from day one (`ttl-days = 30` default in
  config, §4) but the enforcing daily GC cron (sweep storage for old images, delete objects,
  clear `vision_url` rows) is a **FOLLOW-UP**; iteration 1 ships with no GC running.
  `/storage` is gitignored and `[application] root-dir = "storage"` keeps runtime state
  project-local (deployment constraint: nothing outside the project dir).

### 3.3 Normalization — at store time, once

- Where: inside `_processMediaV2`, before the store call. Send-time is the wrong place: it
  would re-pay Pillow decode on every request and would force storing originals.
- New helper `normalizeVisionImage(...)` next to `convertImageIfNeeded` in
  [`lib/ai/models.py`](../../lib/ai/models.py) (lib layer, no bot deps):
  - long side ≤ `max-image-dimension` px (default 2048, LANCZOS, never upscale). 2048 is
    OpenAI's own ceiling; Anthropic recommends 1568 and Gemini accepts 3072 — providers
    downsize server-side anyway, so one conservative default suffices;
  - re-encode to `image-format` (default `image/jpeg`) at `image-quality` (default 85);
  - reuse the decompression-bomb guard concept (`MAX_VISION_IMAGE_PIXELS = 50_000_000`,
    `lib/ai/models.py:75`);
  - never-raise contract: on any failure, return the ORIGINAL bytes unchanged, mirroring
    `convertImageIfNeeded` (`lib/ai/models.py:78-151`).
- One storage format is fine: send-time `convertImageIfNeeded` already re-encodes to whatever
  each model's `input_image_format` demands; a lossless re-encode satisfies PNG-only models.
- Animated content (GIF/WebP sticker): take the first frame, then flatten. Alpha is
  flattened to RGB for JPEG exactly as `convertImageIfNeeded` does
  (`lib/ai/models.py:140-141`).
- Non-image media is untouched — vision engages only for `mediaType in (IMAGE, STICKER)`,
  mirroring the `needParseImage` gate (`base.py:1998-2001`).
- Privacy: Pillow re-save strips EXIF (GPS/device data) — document as a feature.
- **RATIFIED**: stickers included — treated as images throughout the stack.

### 3.4 Context placement

- Same user message, multipart: keep the existing `formatForLLM` JSON envelope (or TEXT
  format) as the text part; append `image_url` blocks AFTER it, in album order.
- The text+image rejection issue was observed with image-PARSING models via OpenRouter
  (hence `content=""` in `_parseImage`, comment at `base.py:2092-2095`) — modern chat models
  declaring `support_image_input` expect exactly this shape. No config escape hatch in
  iteration 1; if a rogue model still rejects it, splitting into adjacent messages becomes a
  per-model param later.
- Multiple images (Max multi-attachment; Telegram albums = N messages sharing
  `media_group_id`, re-expanded at render,
  [`ensured_message.py`](../../internal/bot/models/ensured_message.py):854-862): all image
  blocks in the SAME user message, after the text part. This requires a new multi-image
  message class `ModelImagesMessage`, sibling of `ModelImageMessage` (which holds a single
  `image: bytearray`, `lib/ai/models.py:819-831`).
- History: **RATIFIED** — attach images ALWAYS when stored bytes exist: current turn,
  reply-parent, and all history turns. The cap `max-images-per-request = 5` (default) is the
  primary token/cost guard: attach the MOST-RECENT N images across the context; overflow
  images degrade to their text descriptions. Image tokens (~1-3k per image at 2048 px) are
  invisible to the char-based token estimator — the cap is the only real guard; log when it
  trips.
- Attach eligibility: BOTH the primary AND the fallback chat model must declare
  `support_image_input`. One message list is serialized for both attempts
  (`llm_messages.py:209-226`); a text-only fallback would hard-error on `image_url` parts.
  This feature becomes the flag's first real request-time consumer.

### 3.5 Flow changes

Receipt — in `_processMediaV2` (`base.py:1879`):

- When `native-vision` is on and the mediaType is eligible, ensure the download happens EVEN
  IF `save-attachments` and `parse-attachments` are both off (today bytes are downloaded
  only for save, `base.py:1987-1996`, or for parse, `base.py:2046-2051`).
- Normalize → store under the `vision/` prefix → write `vision_url`. The store step is
  synchronous in `_processMediaV2` (only the LLM parse task is backgrounded,
  `base.py:2102-2105`), so the bytes exist by chat time.

Chat time — in `LLMMessageHandler` message assembly:

- Current message: `llm_messages.py:781-788`; history: `getThreadByMessageForLLM`
  (`base.py:786`) + `fromDBChatMessage` → `formatForLLM`.
- When the setting is on + eligibility holds + `vision_url` bytes load → emit
  `ModelImagesMessage` instead of plain `ModelMessage`.

**RATIFIED follow-up (NOT iteration 1)**: skip the up-to-300 s `_awaitMedia` description
wait (`MAX_MEDIA_AWAIT_SECS = 300`, `ensured_message.py:52`, reached via `updateMediaContent`
during `formatForLLM`) when attaching natively — it needs new `waitForPending`-style
plumbing; no such mechanism exists today. Accepted consequence for iteration 1: with
`parse-attachments` ON + vision ON, chat still waits for pending descriptions exactly as
today.

**RATIFIED**: download + normalize at receipt on BOTH platforms, never re-download later
(Max `file_id` is a CDN URL with unverified expiry — store-at-receipt is the mitigation; if
bytes are gone, fall back to descriptions).

`/analyze`: out of iteration 1 — it already sends native images to the parsing model
([`media.py`](../../internal/bot/common/handlers/media.py):528-567); normalize-helper reuse
is a follow-up.

### 3.6 Fallback matrix

| Scenario | Behavior |
| --- | --- |
| `native-vision` off | Exact status quo: descriptions only, gated by `parse-attachments`. |
| Vision on; both chat models vision-capable; normalized bytes available | Native attach: `ModelImagesMessage` (text part + image blocks) to the chat model. |
| One or both chat models lack `support_image_input` | Description path, including the description wait. |
| Bytes unavailable (null storage / store failed / image pre-dates feature / TTL-expired) | Description path — or absent if `parse-attachments` is off. Accepted consequence: switching a parse-off chat to a non-vision model later leaves those turns with an empty `mediaDescription`. |
| More images in context than `max-images-per-request` | Most-recent N attached natively; overflow images degrade to their text descriptions. |

## 4. Config Sketch

New file `configs/00-defaults/vision.toml`:

```toml
# configs/00-defaults/vision.toml — new file
[bot.vision]
max-image-dimension = 2048   # long-edge px cap, never upscales; 0 = no resize
image-format = "image/jpeg"  # "image/jpeg" | "image/png"
image-quality = 85           # JPEG quality 1-95, ignored for PNG
store-prefix = "vision/"     # StorageService key prefix for normalized images
max-images-per-request = 5   # hard cap on images attached to one LLM request
ttl-days = 30                # retention for stored vision images (enforced by follow-up GC cron)
```

Read via a new `ConfigManager.getVisionConfig()` mirroring `getStorageConfig()`
([`internal/config/manager.py`](../../internal/config/manager.py):405-450). Plus
`[bot.defaults] native-vision = false` in
[`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml).

## 5. Migration Sketch

- Number **030** (verified free: highest existing is migration_029). Follow the
  add-database-migration recipe (`.agents/skills/add-database-migration/SKILL.md`) —
  executed through `BaseSQLProvider`, not raw sqlite3.
- Body: a single portable ALTER:

```sql
ALTER TABLE media_attachments ADD COLUMN vision_url TEXT
```

- Nullable, no default — portable across SQLite/PostgreSQL/MySQL; no `AUTOINCREMENT`, no
  `DEFAULT CURRENT_TIMESTAMP` (AGENTS.md SQL rules; see the
  [SQL portability guide](../sql-portability-guide.md)).
- The dual schema docs
  ([`database-schema.md`](../database-schema.md) and
  [`database-schema-llm.md`](../database-schema-llm.md)) are updated in Phase 3, not with
  the migration.

## 6. Phasing

- **Phase 1a — inert infrastructure**: `normalizeVisionImage` + unit tests; `[bot.vision]`
  config block + `getVisionConfig()`; migration 030.
- **Phase 1b — setting + store**: `NATIVE_VISION` 4-site wiring; `_processMediaV2` vision
  store branch (download-even-if-both-off, normalize, store, `vision_url` write);
  null-backend warnings (configure-time + rate-limited runtime); tests. Still inert at chat
  time.
- **Phase 2 — chat time**: `ModelImagesMessage`; attach-always history assembly with the
  most-recent-N cap; both-models eligibility rule; fallback-matrix tests.
- **Phase 3 — docs sync**:
  [`docs/database-schema.md`](../database-schema.md) AND
  [`docs/database-schema-llm.md`](../database-schema-llm.md) AND
  [`docs/llm/database.md`](../llm/database.md) (schema change);
  [`docs/llm/handlers.md`](../llm/handlers.md) (receipt + chat-time flow);
  [`docs/llm/configuration.md`](../llm/configuration.md) (`vision.toml` + the new setting);
  [`docs/llm/libraries.md`](../llm/libraries.md) (`normalizeVisionImage`,
  `ModelImagesMessage`); [`docs/llm/architecture.md`](../llm/architecture.md) (ADR);
  `CHANGELOG.md`.

## 7. Follow-ups Backlog
- Daily GC cron: sweep storage for images older than `ttl-days`, delete objects, clear
  `vision_url` rows. *(2026-10-04: DONE — implemented as the hourly
  `HandlersManager._visionGcCronJob`, not a daily cron (first pass right after startup);
  see the ADR-027 annotation in [`docs/llm/architecture.md`](../llm/architecture.md) and
  [`docs/llm/handlers.md`](../llm/handlers.md) §9.7.)*
- Skip-300 s-wait plumbing: `waitForPending`-style mechanism in
  `updateMediaContent`/`formatForLLM` so natively-attached images do not block on pending
  descriptions. *(2026-09-27: DONE — implemented differently by native-vision v2: images
  attach at message-construction time; on full attachment, the construction path skips
  the description wait and defers resolution until compaction; partial albums retain the
  description-bearing path — see ADR-028 and
  [`docs/design/native-vision-v2-construction-attach.md`](native-vision-v2-construction-attach.md).)*
- `/analyze` reuse of `normalizeVisionImage` (store-side normalized bytes for the parsing
  model too). *(2026-10-04: DONE — implemented as the LENIENT `normalizeVisionImage`
  wrapper in `analyze_command` (`internal/bot/common/handlers/media.py`): every
  downloaded `image/*` payload is re-normalized with the same cached `[bot.vision]`
  settings before the describe-model request — best-effort (ORIGINAL bytes on any
  failure), nothing stored, no `vision_url` write, and stored vision bytes are NOT
  re-read; see [`docs/llm/handlers.md`](../llm/handlers.md) §9.3.)*
- History variants: attach-last-N-turns windows and similar refinements over the
  attach-always default.
## 8. References

- [`docs/llm/memories/vision-flag.md`](../llm/memories/vision-flag.md) — the completed
  `support_image_input` flag arc this design builds on.
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR record; the ADR for this
  feature lands in Phase 3.
- [`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md), section "Native vision arc
  (2026-09-26, design RATIFIED by user)" — the compact verified fact base with file:line
  anchors.
- [`.agents/skills/add-chat-setting/SKILL.md`](../../.agents/skills/add-chat-setting/SKILL.md) —
  4-site chat-setting wiring recipe.
- [`docs/sql-portability-guide.md`](../sql-portability-guide.md) — cross-RDBMS rules the
  migration must follow.
- Code entry points:
  [`lib/ai/models.py`](../../lib/ai/models.py),
  [`lib/ai/abstract.py`](../../lib/ai/abstract.py),
  [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py),
  [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py),
  [`internal/bot/common/handlers/llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py),
  [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py),
  [`internal/bot/models/ensured_message.py`](../../internal/bot/models/ensured_message.py),
  [`internal/services/storage/service.py`](../../internal/services/storage/service.py),
  [`internal/config/manager.py`](../../internal/config/manager.py).
