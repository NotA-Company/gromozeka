---
category: design
---

# Native Vision v2 — Construction-Time Image Attach

**Author:** OpenCode Architect
**Date:** 2026-09-27
**Status:** Ratified 2026-09-27 — implemented

Supersedes the chat-time mechanism of
[`native-vision-design-v1.md`](native-vision-design-v1.md) §3.4/§3.5 (the late
`_applyNativeVision` swap). All v1 decisions not explicitly changed here stand:
receipt-time store, normalize-once/strict contract, EXIF handling, both-models
eligibility, fail-soft layers, conditional condenser strip.

---

## 1. Overview

### 1.1 Goal

Move native image attachment from the single late chokepoint
(`LLMMessageHandler._applyNativeVision`, run inside `_sendLLMChatMessage` after
assembly) **into message construction itself** (`EnsuredMessage.toModelMessage`),
and make the construction path skip the media-description wait when images
attach. The description is not lost: it moves into a **lazy resolver** attached
to the built `ModelMessage`, invoked only if the condenser ever needs the text
(compaction is rare, so the up-to-300 s wait almost never happens).

Net effects:

1. Attached images no longer pay the up-to-300 s `_awaitMedia` description wait
   at assembly time ([`ensured_message.py`](../../internal/bot/models/ensured_message.py):1111,
   `MAX_MEDIA_AWAIT_SECS = 300` at :52).
2. The model no longer sees both the image AND its full text description for
   the same media (dedup on the attach path).
3. The condenser (text-only condensing models) still learns what the image
   contained — via the resolver at strip time, with today's omission marker as
   fallback.
4. The request-wide `max-images-per-request` cap is **removed** (ratified;
   re-add later only if real-chat testing demands it).

### 1.2 Why now

v1's late swap was ratified as the minimal-delta design, but it runs *after*
`formatForLLM` has already paid the description wait, and the swap machinery
(source-pairing walker, cap loop, per-message DB re-fetch of `vision_url`) is
the most complex part of the v1 chat-time path
([`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):184-299).
Construction-time attach collapses that machinery into the one place that
already knows the media: the `EnsuredMessage` being rendered.

## 2. Current State (verified against working tree 2026-09-27)

All anchors re-verified on top of uncommitted working-tree changes.

- **Attach happens at exactly one late chokepoint.**
  `_sendLLMChatMessage` ([`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):404)
  calls `_applyNativeVision(messagesHistory, chatSettings=...)` at :454, after
  assembly. `_applyNativeVision` (:184-299) walks the assembled list
  newest→oldest, pairs each `ModelMessage` with its `EnsuredMessage` via
  `.source`, loads `vision_url` per media (`_getVisionUrl` :139-164 — direct
  `db.mediaAttachments.getMediaAttachment` re-fetch, no cache), loads bytes
  (`_loadVisionBytes` :166-182), and swaps `ModelMessage` → `ModelImagesMessage`
  (:287-290) keeping envelope text, `source`, `weight`.
- **Eligibility** is inlined in `_applyNativeVision` (:231-245): NATIVE_VISION
  on (:222-223) AND `resolveModel(CHAT_MODEL)` AND `resolveModel(FALLBACK_MODEL)`
  both report `getInfo()["support_image_input"]`; any resolution failure fails
  soft to descriptions (:240-242).
- **Cap**: `self._maxImagesPerRequest` cached in `LLMMessageHandler.__init__`
  (:130-132) from `getVisionConfig().get("max-images-per-request",
  DEFAULT_MAX_IMAGES_PER_REQUEST)`; `DEFAULT_MAX_IMAGES_PER_REQUEST = 5` at
  [`internal/bot/constants.py`](../../internal/bot/constants.py):330. Capacity
  is consumed only by successfully loaded bytes (:276-283); one WARNING on trip
  (:293-297).
- **The description wait is assembly-time and always precedes attach today.**
  `toModelMessage` ([`ensured_message.py`](../../internal/bot/models/ensured_message.py):1279-1337)
  → `formatForLLM` (:1064-1205) unconditionally awaits `updateMediaContent(db)`
  at :1111, which awaits per-media processing tasks and polls `_awaitMedia`
  (:974-999; `_awaitMedia` :1012-1062, 2.5 s interval, 300 s budget). `handleReply`
  has an EXTRA eager `updateMediaContent` at
  [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):780.
- **Render shapes**: JSON envelope emits `"mediaDescription": mediaContent`
  (:1185; falsy values dropped by the `if v` filter at :1188); TEXT form
  prepends `<media-description>...</media-description>` when `self.mediaContent`
  is truthy (:1196-1197). Note the guard reads the *attribute*, which may be
  pre-populated at construction (e.g. `fromDBChatMessage` sets it from the
  stored description at :862) — relevant to §4.2.
- **`toModelMessage` has no service access.** No `chatSettings`, no
  `llmService`, no storage. Runtime `llmService` import is a hard cycle:
  [`internal/services/llm/service.py`](../../internal/services/llm/service.py):17-18
  imports `EnsuredMessage` (same wall as the CacheService `TYPE_CHECKING`
  comment at [`ensured_message.py`](../../internal/bot/models/ensured_message.py):44-48).
  `db` IS a per-call parameter (ADR-018 keyword-threading precedent:
  `cache`/`excludeMemoryIds`).
- **`ModelMessage.source` is the metadata-field precedent.**
  [`lib/ai/models.py`](../../lib/ai/models.py): `__slots__` at :467 includes
  `source`; `__init__` :469-499; `fromDict` :502-576 and `toDict` :597-658
  never serialize it → invisible to providers, estimator, `toLogMessage`
  (:676-697), tools-DB round-trips. `ModelImagesMessage` (:824) calls
  `super().__init__(role, content)` positionally (:856).
- **Condenser**: `condenseContext`
  ([`internal/services/llm/service.py`](../../internal/services/llm/service.py):1203)
  strips image-bearing **body** messages ONLY when the condensing model lacks
  `support_image_input` (fail-soft probe :1327-1331; gate :1332-1333 — a list
  comprehension calling the SYNC module-level `stripImagesForCondensing`
  :182-226, which preserves role/content/contentKey/weight/source and appends
  the count-aware marker :150-159 only when `_contentCarriesMediaDescription`
  (:162-179) is false). `retHead`/`retTail` keep images; the truncation path
  (no condensing model, :1302-1315) never strips. `generateTextViaLLM`'s
  per-round condense (:1003-1014) funnels through the same `condenseContext`.
- **StorageService is cycle-free from `internal.bot.models`**: singleton via
  `getInstance()` ([`internal/services/storage/service.py`](../../internal/services/storage/service.py):83-91),
  imports only its own backends + `TYPE_CHECKING` ConfigManager (:8-19); `get`
  is sync (:237-259) and raises `StorageConfigError` via `_ensureInitialized`
  (:252) when never injected.
- **Consumer census (production, 10 `toModelMessage` sites)**: 9 chat-path —
  `getThreadByMessageForLLM` ×3
  ([`base.py`](../../internal/bot/common/handlers/base.py):857/:900/:949; def :806;
  callers: handleReply :785, handleRandomMessage thread branch :1057), handleReply
  fallback pair (llm_messages.py :802/:808 — live parent, empty `mediaList`),
  handleMention (:941 TEXT live parent — never has `mediaList`; :962 DB parent —
  HAS `mediaList`; :972 current), handleRandomMessage window :1104 + current
  :1155. **1 non-chat site**: [`media.py`](../../internal/bot/common/handlers/media.py):686
  (`_llmToolGenerateImage` prompt fallback) — must NOT receive images.
  **5 direct `formatForLLM` sites that must stay description-bearing**:
  [`summarization.py`](../../internal/bot/common/handlers/summarization.py):215,
  [`chat_search.py`](../../internal/bot/common/handlers/chat_search.py):546 (embeddings)
  and :854 (get_thread tool output),
  [`user_memories.py`](../../internal/bot/common/handlers/user_memories.py):1532,
  [`message_preprocessor.py`](../../internal/bot/common/handlers/message_preprocessor.py):210.
- **Assembly-time condense callers** (they see constructed messages, so under
  v2 they see image messages + resolvers): thread path
  [`base.py`](../../internal/bot/common/handlers/base.py):977/:997 (summaries
  persisted to `metadata["condensedThread"]` :1017-1022), random window
  [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):1129-1140
  (summary persisted to `metadata["randomContext"]` :1144-1150), per-round
  service.py :1003, dev script
  [`scripts/check_condensing.py`](../../scripts/check_condensing.py):609.

## 3. Ratified decisions (user, 2026-09-27, m0101)

1. **Fully move image attachment into `EnsuredMessage`.** `formatForLLM` gains
   `skipMediaDescription: bool = False` (True when vision is enabled).
   `toModelMessage` gains `nativeImages: bool = False` — when True: attach
   native images AND skip media-description.
2. **Drop the most-recent-N request-wide image cap entirely for now.** The user
   will re-add after testing on a real chat if needed. (Sweep the constant,
   config key, docs, tests on removal.)
3. **300 s description wait:** with native vision on, do NOT wait for the media
   description. Pass onto the created `ModelMessage` not a resolved description
   but a **handler (callable) which resolves the description (and waits inside
   it)** — invoked lazily at compaction time. Since compaction is rare, the
   wait will almost never happen. Condenser injects the real description;
   today's marker stays as the fallback when the resolver yields nothing.

## 4. Detailed Design

### 4.1 `ModelMessage.descriptionResolver` (new field)

- Name: **`descriptionResolver`**. Type (no `Any`, camelCase per AGENTS.md §3):

  ```python
  # lib/ai/models.py — add `from collections.abc import Awaitable, Callable` at file top
  descriptionResolver: Optional[Callable[[], Awaitable[Optional[str]]]]
  ```

  Optional module-level alias for readability (mirrors the `LLMToolHandler`
  TypeAlias pattern in service.py:46):
  `ModelMessageDescriptionResolver: TypeAlias = Callable[[], Awaitable[Optional[str]]]`.

- Add to `__slots__` (models.py:467) and to `__init__` as a trailing
  keyword-only-ordered parameter with default `None` (positioned after
  `source`, :477). `ModelImagesMessage.__init__` (:844-857) gains
  `descriptionResolver=None` (and `source=None`, needed by §4.3) passed through
  to `super().__init__`. `ModelImageMessage` is intentionally untouched
  (single-image parse path never skips descriptions).
- **Serialization contract — mirror `source` exactly**: never emitted by
  `toDict` (:597-658), never read by `fromDict`/`fromDictList` (:502-576), not
  in `toLogMessage` (:676-697), hence invisible to providers, the token
  estimator, JSON logs, and the tools-DB round-trip. It is never *copied*
  anywhere implicitly: the only deliberate consumer is the condenser strip
  (§4.6); `stripImagesForCondensing`'s output message carries
  `descriptionResolver=None` (it was consumed there). Post-assembly rebuilds
  (`ModelRunResult.toModelMessage`, steering system rebuild) construct fresh
  messages without it — correct, those are assistant-side artifacts.
- Semantics contract for the callable: returns the resolved media description
  for the source message (possibly after waiting), or `None`/empty when nothing
  resolves; **at most one effective invocation per closure** (§4.4); must never
  raise (implementation wraps in try/except).

### 4.2 `formatForLLM(skipMediaDescription=...)`

New keyword-only parameter `skipMediaDescription: bool = False`. When **True**:

1. **Skip the wait entirely**: do NOT call `await self.updateMediaContent(db)`
   (today unconditional at
   [`ensured_message.py`](../../internal/bot/models/ensured_message.py):1111).
   This skips both the per-media `processingInfo.awaitResult()` (:985-987) and
   the `_awaitMedia` polling (:989, :996).
2. **Render without the description**: JSON branch omits the
   `"mediaDescription"` key (force the local `mediaContent` to `None`; the
   `if v` filter at :1188 already drops it). TEXT branch must NOT prepend the
   `<media-description>` block — **trap**: today's guard at :1196 checks
   `self.mediaContent` (the attribute), which can be pre-populated (e.g.
   `fromDBChatMessage` :862, or `addMedia` at :953). The guard must become
   `if not skipMediaDescription and self.mediaContent:` (or equivalent local
   suppression). Spec this explicitly for the implementer.
3. `useSingleMedia` selection (:1112-1114) is moot on the skip path (no
   `mediaContent` is selected at all).

When **False** (default): byte-for-byte today's behavior. All five non-chat
direct `formatForLLM` callers (§2 census) keep the default — descriptions and
waits intact there. `toModelMessageList` does NOT gain `skipMediaDescription`
(it is not a render knob callers should thread; the skip is decided inside
`toModelMessage`'s vision sequencing, §4.3).

### 4.3 `toModelMessage(nativeImages=...)` — sequencing and the album rule

New keyword-only parameter `nativeImages: bool = False`, forwarded 1:1 by
`toModelMessageList` (new kwarg of the same name, passed at its main-message
call site
[`ensured_message.py`](../../internal/bot/models/ensured_message.py):1264-1276).

Algorithm (exact order — bytes BEFORE render, so the description fallback
stays safe):

```python
# after the existing SMART format resolution (:1316-1322)
if nativeImages and self.mediaList:
    images, allDescribedAttached = await self._loadNativeVisionImages(db)  # NEVER raises
else:
    images, allDescribedAttached = [], False

if images and allDescribedAttached:
    # SKIP PATH — no description wait:
    content = await self.formatForLLM(db, ..., skipMediaDescription=True)
    return ModelImagesMessage(role=role, content=content, images=images,
                              source=self, descriptionResolver=self._makeDescriptionResolver(db))

content = await self.formatForLLM(db, ...)  # default path — wait happens HERE if pending
if images:  # PARTIAL — attach what loaded, keep the description in the envelope
    return ModelImagesMessage(role=role, content=content, images=images, source=self)
return ModelMessage(role=role, content=content, source=self)  # description-only (today's :1324-1337)
```

`_loadNativeVisionImages(db) -> Tuple[List[bytearray], bool]` — a private
`EnsuredMessage` helper wrapped in ONE never-raise `try/except Exception`
(mirroring `_storeVisionImage`'s fail-soft style,
[`base.py`](../../internal/bot/common/handlers/base.py):2226-2283; on exception:
log `logger.debug`, return `([], False)`):

1. `storage = StorageService.getInstance()` (§4.5).
2. For each `media` in `self.mediaList` (album order):
   `row = await db.mediaAttachments.getMediaAttachment(media.id)`.
   - `row is None` → **ghost** (no row; can never carry a description —
     `_awaitMedia` returns `None` immediately on a missing row,
     [`ensured_message.py`](../../internal/bot/models/ensured_message.py):1030-1032).
   - `row["vision_url"]` truthy → candidate: `data = storage.get(url)`;
     truthy → **attached** (`bytearray(data)`), else **describable-not-attached**.
   - row without `vision_url` → **describable-not-attached**.
3. Returns `(attachedImages, allDescribableAttached)` where
   `allDescribableAttached = attached non-empty AND every non-ghost entry attached`.

**Album rule (crisp, ratified recommendation):** skip the description ONLY
when **every `mediaList` entry that has a `media_attachments` row yielded
loadable vision bytes**. Ghost entries never block the skip (they can never
produce a description). Otherwise keep the description; when some bytes DID
load, attach the loaded subset **alongside** the description-bearing envelope.

- Rationale (conservative, information-maximal, v1 parity): a partially-loaded
  album whose description is dropped would silently lose the unattached media
  entirely; keeping the description costs only dedup for the attached subset —
  exactly what v1 did (the v1 swap always kept the description-bearing envelope;
  pinned by `testBytesUnavailableMessageStaysPlainOthersStillAttach`,
  [`tests/bot/common/handlers/test_llm_messages.py`](../../tests/bot/common/handlers/test_llm_messages.py):2232-2270).
- No-resolver on the partial path: the envelope already carries the
  descriptions, so the condenser's `_contentCarriesMediaDescription` gate
  (service.py:162-179) needs nothing.
- The never-raise boundary wraps ONLY the vision attempt. `formatForLLM` and
  the return construction stay outside it, preserving today's error contract.

### 4.4 The lazy resolver closure

Private helper on `EnsuredMessage`:

```python
def _makeDescriptionResolver(self, db: Database) -> Callable[[], Awaitable[Optional[str]]]:
    """Build an at-most-once lazy description resolver for this message."""
    resolved: Optional[str] = None
    resolvedOnce: bool = False

    async def resolve() -> Optional[str]:
        nonlocal resolved, resolvedOnce
        if resolvedOnce:
            return resolved
        resolvedOnce = True
        try:
            await self.updateMediaContent(db)  # waits INSIDE, up to 300 s per pending media
            descriptions = [v.content for v in self.mediaList if v.content]
            resolved = "\n".join(descriptions) if descriptions else None
        except Exception as e:
            logger.debug(f"Native vision description resolution failed: {type(e).__name__}#{e}")
            resolved = None
        return resolved

    return resolve
```

- The closure can literally reuse `updateMediaContent`
  ([`ensured_message.py`](../../internal/bot/models/ensured_message.py):974-999)
  — it is an `EnsuredMessage` method and `db` is captured; it performs the
  identical waits `formatForLLM` would have performed (:1111). `updateMediaContent`
  mutates `self.mediaList[*].content` / `self.mediaContent` idempotently
  (cache-fill), so calling it later is safe even if something else already did.
- **Aggregation**: join non-empty per-media descriptions with `"\n"`; empty
  result → `None` (marker fallback downstream). This is the album-aware
  superset of the `useSingleMedia` selection — the condenser wants everything.
- **At-most-once per message per request**: the closure caches after the first
  call. Condense rounds that strip the same message repeatedly
  (`generateTextViaLLM` re-condenses every round, service.py:1003-1014) pay the
  wait once; subsequent rounds get the cached value. One closure is created per
  `toModelMessage` call, so the same `EnsuredMessage` rendered twice in one
  request (does not happen on current paths) would create two closures —
  acceptable, each still at-most-once.

### 4.5 Storage access in `ensured_message.py`

**Recommendation: (a) `StorageService.getInstance()` lazily inside the vision
branch, with a module-level import at file top** (repo rule: imports at file
top; AGENTS.md).

- No cycle: [`internal/services/storage/service.py`](../../internal/services/storage/service.py)
  imports only `.backends.*`/`.exceptions` plus `TYPE_CHECKING` ConfigManager
  (:8-19) — nothing from `internal.bot`. This is unlike `llmService`
  (hard cycle, service.py:17-18) and `CacheService` (TYPE_CHECKING-only,
  ensured_message.py:44-48).
- Matches the repo singleton rule (`Service.getInstance()`, never
  `Service()`) and how `BaseBotHandler` itself obtains storage
  ([`base.py`](../../internal/bot/common/handlers/base.py):166).
- Rejected (b) optional `storage` param threaded like `db`: it would touch all
  10 production call sites + the `toModelMessageList` chain to pass a value the
  sanctioned singleton accessor already yields, doubling the threading surface
  added by `nativeImages` for zero decoupling benefit (tests can patch
  `StorageService.getInstance` — precedent at
  [`tests/bot/common/handlers/test_llm_messages.py`](../../tests/bot/common/handlers/test_llm_messages.py):2034).
- **Test impact**: un-injected singleton → `storage.get` raises
  `StorageConfigError` (`_ensureInitialized`, service.py:252) → swallowed by
  the §4.3 never-raise boundary → no bytes → description path (fail-soft).
  Null backend → `get` returns `None` → same. No test is forced to configure
  storage; vision-attach tests inject/patch as needed.

### 4.6 Condenser: async strip + resolver injection

- `stripImagesForCondensing` becomes **`async def`**
  ([`internal/services/llm/service.py`](../../internal/services/llm/service.py):182-226);
  signature otherwise unchanged. New body:

  ```python
  async def stripImagesForCondensing(message: ModelMessage) -> ModelMessage:
      if not isinstance(message, (ModelImageMessage, ModelImagesMessage)):
          return message
      content = message.content
      if not _contentCarriesMediaDescription(content):
          resolved: Optional[str] = None
          if message.descriptionResolver is not None:
              resolved = await message.descriptionResolver()
          if resolved:
              content += f"\n<media-description>{resolved}</media-description>"
          elif isinstance(message, ModelImagesMessage):
              content += _STRIPPED_IMAGES_MARKER_TEMPLATE.format(...)  # unchanged :215-217
          else:
              content += _STRIPPED_IMAGE_MARKER                    # unchanged :219
      return ModelMessage(role=message.role, content=content,
                          contentKey=message.contentKey, weight=message.weight,
                          source=message.source)  # descriptionResolver deliberately NOT copied
  ```

- **Injected format**: the resolved description is wrapped in
  `<media-description>…</media-description>` — the same tag the TEXT envelope
  uses (ensured_message.py:1197), so the condenser reads one consistent
  vocabulary. Marker fallback (resolver absent, `None`, empty — timeout, parse
  failure, pre-feature media) is today's count-aware marker **verbatim**
  (:153/:159).
- **Call-site change** (the only production one) in `condenseContext` :1333:

  ```python
  body = list(await asyncio.gather(*(stripImagesForCondensing(v) for v in body)))
  ```

  `service.py` currently has **no `asyncio` import** (:8-12) — add
  `import asyncio`. `asyncio.gather` matters: resolver waits for multiple
  pending albums run concurrently (worst case one 300 s window, not N×300 s
  serial), and order is preserved.
- The strip gate (:1317-1333) is unchanged: text-only condensing models strip
  (and thus consume resolvers); vision-capable condensers see image messages
  untouched and resolvers stay **uninvoked**; the truncation path (:1302-1315)
  never strips. `retHead`/`retTail` keep images and resolvers (they go to the
  chat model).
- All `condenseContext` callers are already async and its signature does not
  change: service.py:1003 (per-round), base.py:977/:997 (thread),
  llm_messages.py:1129 (random window), scripts/check_condensing.py:609 (dev).
- **Assembly-time condense interplay (confirmed acceptable, document)**: the
  random-window direct condense (llm_messages.py:1129-1140) and the thread-path
  condenses (base.py:977/:997) now receive image messages + resolvers. With a
  text-only condenser, summaries — including the ones persisted to
  `metadata["randomContext"]` (:1144-1150) and `metadata["condensedThread"]`
  (:1017-1022) — are built from REAL resolved descriptions (or markers), which
  is information-parity with today (today those paths condensed envelopes that
  already carried descriptions). The rare cost: a pending-media wait can now
  happen at condense time instead of render time — and only when the context is
  actually over the condense threshold.

### 4.7 Eligibility helper + flag threading

- New private method on `LLMMessageHandler`
  ([`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py)):

  ```python
  def _nativeVisionEnabled(self, chatSettings: ChatSettingsDict) -> bool:
      """NATIVE_VISION on AND both chat models vision-capable (fail-soft)."""
  ```

  Body = the NATIVE_VISION check (:222-223) + the both-models block **moved
  verbatim** from `_applyNativeVision` :231-245 (same `resolveModel` keys and
  `defaultKey`s, same `.get("support_image_input", False)` bool checks, same
  except→WARNING→False fail-soft). The both-models rule itself is ratified v1
  and preserved unchanged: one list is serialized for the primary AND the
  fallback attempt, so a text-only fallback would hard-error on `image_url`
  parts.
- Resolved **once per request** at trigger entry, then threaded as
  `nativeImages=True`:

  | Site | File:line | Change |
  | --- | --- | --- |
  | `handleReply` entry | llm_messages.py :735/:765 | compute `nativeVision = self._nativeVisionEnabled(chatSettings)` before the typing block (:778) |
  | reply eager wait | llm_messages.py :780 | `if not nativeVision: await ensuredMessage.updateMediaContent(self.db)` (§4.8) |
  | thread assembly call | llm_messages.py :785 | pass `nativeImages=nativeVision` |
  | reply fallback parent (live) | llm_messages.py :802 | pass flag (no-op today — live bot reply has empty `mediaList`; uniformity) |
  | reply fallback current | llm_messages.py :808 | pass flag (this is the fresh-media message) |
  | `handleMention` entry | llm_messages.py :831 (chatSettings already fetched above :905) | compute flag once |
  | mention TEXT live parent | llm_messages.py :941 | pass flag (never has `mediaList`; harmless, keeps wiring uniform) |
  | mention DB parent | llm_messages.py :962 | pass flag (HAS `mediaList`; SMART→TEXT for assistant role still skips the prepend per §4.2) |
  | mention current | llm_messages.py :972 | pass flag |
  | `handleRandomMessage` entry | llm_messages.py :989/:1044 | compute flag once |
  | random thread branch | llm_messages.py :1057 | pass `nativeImages=nativeVision` |
  | random window rows | llm_messages.py :1104 | pass flag (feeds BOTH the request and the direct condense :1129) |
  | random current | llm_messages.py :1155 | pass flag |
  | `getThreadByMessageForLLM` | base.py :806 | new kwarg `nativeImages: bool = False`, threaded to its 3 render sites :857/:900/:949 |
  | `toModelMessageList` | ensured_message.py :1207 | new kwarg, forwarded at :1264-1276 |
  | `toModelMessage` | ensured_message.py :1279 | new kwarg (implementation, §4.3) |

- **Non-chat callers keep defaults**: media.py:686 (`_llmToolGenerateImage`
  prompt fallback) gets NO flag → no images (would otherwise leak bytes to a
  10-message `generateText` call, media.py:695-702), descriptions intact. The
  five direct `formatForLLM` sites keep `skipMediaDescription=False` (§4.2).
- Role-independence is preserved structurally: any `EnsuredMessage` with
  `mediaList` renders images under the flag regardless of role (mention DB
  parent with `role="assistant"` attaches, matching v1's role-agnostic swap);
  system/tool messages are never built from an `EnsuredMessage` source, so they
  are excluded naturally.

### 4.8 `handleReply` eager wait gating

Gate the eager `updateMediaContent` (llm_messages.py:780) on the flag
(§4.7 table). **Fallback guarantee (verified)**: if construction later takes
the description path (no bytes), `formatForLLM`'s internal
`await self.updateMediaContent(db)` at
[`ensured_message.py`](../../internal/bot/models/ensured_message.py):1111 still
runs — v2 keeps that line unconditional on the non-skip path — so the wait is
**deferred to construction, not lost**. The only case where the wait vanishes
entirely is the skip path, where the resolver owns it.

Side note (no action): skipping `updateMediaContent` also skips the
`self.mediaPrompt` refresh (ensured_message.py:999); its sole cross-handler
consumer is the `/analyze` stored-message path
([`media.py`](../../internal/bot/common/handlers/media.py):348), which performs
its own load — not the chat render. Non-issue.

### 4.9 `_sendLLMChatMessage` after the removal

- The `_applyNativeVision` call (:451-454) and its comment are deleted; the
  assembled list flows straight to the debug dump and `_generateTextViaLLM`.
- **Debug dump: KEEP unchanged** (:456-468). It already renders image messages
  via `toLogMessage()` and plain ones via `repr()` under an
  `isEnabledFor(DEBUG)` guard, and has no dependency on the swap mechanism;
  construction-attached `ModelImagesMessage`s render identically.
- The `chatSettings` fetch (:448) stays (still used for `LLM_MESSAGE_FORMAT`,
  `USE_TOOLS`, prefixes).

### 4.10 Style constraints for implementers

camelCase, docstrings with `Args:`/`Returns:` + full type hints, **no pydantic,
no `Any` in new signatures** (`descriptionResolver` is typed
`Optional[Callable[[], Awaitable[Optional[str]]]]`; the pre-existing
`source: Optional[Any]` at models.py:477 is legacy, not a license), imports at
file top, `StrEnum` where applicable. Run `make format lint` and `make test`
before AND after edits (AGENTS.md). Every new behavior gets a regression test
(§8 inventory); every deleted behavior's test is enumerated in §6.

## 5. Edge Cases + Fallback Matrix v2

| Scenario | v2 Behavior |
| --- | --- |
| `native-vision` off (or models ineligible) | Exact status quo: `nativeImages=False` everywhere; descriptions + waits unchanged; zero storage reads, zero `media_attachments` fetches beyond today's. |
| Vision on + eligible + all describable media → bytes | **Attach at construction**: `ModelImagesMessage`, envelope WITHOUT `mediaDescription` (JSON key absent / TEXT prepend absent), NO wait at construction, resolver attached. |
| Partial bytes (some media load, some don't) | **Album rule** (§4.3): attach the loaded subset + envelope WITH description (wait included), no resolver. Cost: attached subset described twice (v1 parity). |
| No bytes at all (null backend / store failed / pre-feature / TTL) | Plain `ModelMessage` with description, including the wait — identical to today. |
| Fresh media still PENDING, skip path taken | No wait anywhere at construction; resolver holds the pending state; if the condenser never runs, the wait never happens. |
| Condense, text-only condensing model | Strip consumes the resolver: real description injected as `<media-description>…</media-description>`; resolver empty/`None` (timeout, parse failed, pre-feature) → today's count-aware marker verbatim. Wait (if any) happens here, once, concurrently across messages via `gather`. |
| Condense, vision-capable condensing model | Image messages pass through untouched; resolver never invoked. |
| Truncation (no condensing model configured) | Images kept (truncation path never strips); resolver never invoked; `generateText` receives images exactly as today's post-swap behavior. |
| Image cap | **REMOVED.** Consequence: an N-image album attaches in full; image tokens are excluded from the estimator's counts by the wave-A object-list fold (ADR-027), so per-request cost is bounded only by album size. Accepted by user; re-adding a cap after real-chat testing is an explicit user follow-up. |
| Same media in two messages | Each render fetches its row + bytes independently (v1 no-urlCache decision preserved; now naturally — two `toModelMessage` calls). |
| Ghost media (no `media_attachments` row) | Never blocks the skip; never attached; `_awaitMedia` returns immediately (ensured_message.py:1030-1032). |
| `media_attachments`/storage raise | Swallowed by the never-raise boundary → description path for that message; send continues. |
| Embeddings / search / summaries / memories / image-prompt fallback | Untouched (defaults `False`): descriptions still rendered and waited on. |

## 6. Deletion List (v1 machinery that dies)

Production code:

- [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py):
  `_applyNativeVision` (:184-299) incl. the source-pairing walker and cap loop;
  `_getVisionUrl` (:139-164); `_loadVisionBytes` (:166-182); the
  `self._maxImagesPerRequest` init block (:128-132); the call + comment in
  `_sendLLMChatMessage` (:451-454); the "Native vision" section banner comment
  (:134-137). Clean up now-unused imports (`Sequence`/`List` if orphaned;
  `constants` alias stays — `ToolName` etc. still used).
- [`internal/bot/constants.py`](../../internal/bot/constants.py): `DEFAULT_MAX_IMAGES_PER_REQUEST` (:330).
- [`configs/00-defaults/vision.toml`](../../configs/00-defaults/vision.toml): the
  `max-images-per-request = 5` line (:9).
- [`internal/config/models.py`](../../internal/config/models.py): the
  `"max-images-per-request": int` `VisionConfigDict` entry (:30) + docstring
  mention. `getVisionConfig()` itself and manager.py:453-486 STAY (receipt-side
  keys still consumed; drop only the cap key from its docstring/example).

Tests (all in [`tests/bot/common/handlers/test_llm_messages.py`](../../tests/bot/common/handlers/test_llm_messages.py)
unless noted):

- **DELETE** `TestVisionCapConstructorWiring` (:1999-2075, 3 tests) — the cap
  wiring it pins is gone.
- **DELETE cap-specific tests** from `TestNativeVisionChatAttach`:
  `testOverCapAttachesMostRecentOnlyAndLogsTrip` (:2400),
  `testOverCapWithinOneAlbumAttachesFirstSlots` (:2446), and the cap half of
  `testStorageMissWithinAlbumLetsLaterImageUseSlot` (:2272) — its
  storage-miss-degradation half is reborn as a partial-album test (§8).
- **REWRITE** the remaining `TestNativeVisionChatAttach` tests (:2078-2654;
  14 survive conceptually) from "_sendLLMChatMessage swaps hand-assembled
  lists" to "toModelMessage(nativeImages=True) attaches at construction":
  vision-off no-op; both-capable attach current+history; primary/fallback
  lacks → no attach + storage never read; bytes-unavailable degrade;
  missing-row degrade; DB-exception degrade; storage-exception degrade;
  resolution-failure fail-soft; assistant-role attach; system/tool natural
  exclusion (now: system messages are simply not built from `EnsuredMessage`);
  same-media-twice refetch; mention wiring; real-stamping test becomes
  trivially real (construction IS the real path; the swap-preservation
  assertion dies with the swap).
- **ADAPT helpers** (:1893-1996): `_enableVision` loses `maxImages` (keeps the
  eligibility wiring, now aimed at `_nativeVisionEnabled` / entry threading);
  `_wireStorage` patches `StorageService.getInstance` (or injects a backend)
  instead of `liveHandler.storage`; `_visionModel`/`_mediaSource`/`_wireMediaRows`
  keep.
- **AWAIT-updates**: [`tests/services/llm/test_strip_images_for_condensing.py`](../../tests/services/llm/test_strip_images_for_condensing.py)
  (all 7 strip call sites :34-147 become `await` + gain resolver cases) and the
  image tests inside
  [`tests/services/llm/test_llm_service.py`](../../tests/services/llm/test_llm_service.py)
  `TestCondenseContextCoverage` (:2021) and `TestCondenseContextImageStripGating` (:2669).
- **KEEP unchanged**: `TestProcessMediaV2Vision` and all receipt-side /
  base-init-vision tests in [`tests/bot/common/handlers/test_base.py`](../../tests/bot/common/handlers/test_base.py)
  (:1664 onward; the base init-cache assertions at :2671-2675 cover
  `BaseBotHandler.__init__` receipt settings, which are NOT deleted — the
  cap-related "two getVisionConfig calls" expectation existed only in
  `TestVisionCapConstructorWiring` and dies with it).

## 7. Config / Docs / CHANGELOG Impact

Executed by the implementation phases (§8); listed here for planning.

- **`docs/llm/handlers.md`**: §9 Native Vision (:617) — rewrite the Chat-time
  flow subsection (:629-635): construction-time attach, eligibility helper,
  no cap, resolver + condenser injection; the `llm_messages.py` file-table row
  (:110) drops its `_applyNativeVision` mention.
- **`docs/llm/architecture.md`**: **recommend a NEW ADR-028** ("Native vision
  v2 — construction-time attach, lazy description resolver, cap removed") that
  marks ADR-027's chat-time mechanism (:1180, :1183 bullets) superseded while
  explicitly reaffirming ADR-027's receipt-side decisions (store, strict
  normalize, EXIF, fail-soft). Rationale: ADR-027 is an accepted, implemented
  historical record with three refinement waves; silently rewriting it would
  destroy the decision trail, and this change inverts a ratified placement
  decision — that is a new decision with new context, not a refinement.
- **`docs/llm/libraries.md`**: §1.1 key-classes table + §1.3 —
  `ModelMessage.descriptionResolver` field, its mirror-`source` serialization
  contract, the at-most-once resolver contract, async
  `stripImagesForCondensing` (:222 paragraph update).
- **`docs/llm/configuration.md`**: remove the `max-images-per-request` row
  (:96) and any cap mention in the `getVisionConfig()` description.
- **`docs/llm/services.md`**: condenser paragraph (:216) — async strip,
  resolver consumption, `<media-description>` injection, marker fallback,
  `gather` concurrency.
- **`docs/database-schema.md` (:480) + `docs/database-schema-llm.md` (:203)**:
  no schema change, but both describe `vision_url` as "read at chat time by
  `LLMMessageHandler._applyNativeVision`" — update the reader name to
  `EnsuredMessage.toModelMessage` (native-vision v2).
- **`CHANGELOG.md`** `[Unreleased]/Changed` sketch: "Native vision: images now
  attach at message-construction time (`EnsuredMessage.toModelMessage`) instead
  of a post-assembly swap; attached images no longer wait for their text
  description (resolved lazily only if the conversation needs compacting);
  removed the `bot.vision.max-images-per-request` cap."
- **Teamlead memory**: note the v2 mechanism + this doc (per
  `update-project-docs` skill).
- `docs/llm/index.md` Key Features bullet: check wording in Phase D (mentions
  native-vision; likely still accurate).

## 8. Phasing and Test Strategy

Each phase is one developer-sized invocation (≤ ~60 steps), ends green on
`make format lint` + `make test`, and leaves the tree shippable.

### Phase A — lib field + async condenser strip (inert)

`ModelMessage.descriptionResolver` (+ `__slots__`, `__init__`, TypeAlias,
`ModelImagesMessage` `source`/`descriptionResolver` kwargs);
`stripImagesForCondensing` → async with resolver consumption + marker
fallback; `condenseContext` gather call-site + `import asyncio`.

Tests: `tests/lib/ai/test_models.py` — field defaults `None`; absent from
`toDict`/`fromDict`/`toLogMessage`; kwargs pass-through on
`ModelImagesMessage`. `tests/services/llm/test_strip_images_for_condensing.py`
— await rewrites; resolver → `<media-description>` injection; resolver
`None`/empty → marker; description-bearing content → resolver NOT invoked
(lazy); called-once caching. `test_llm_service.py` gating tests — await
updates + injection-through-`condenseContext` test.

Acceptance: full suite green with zero production behavior change (resolvers
never exist yet).

### Phase B — `EnsuredMessage` construction attach (opt-in, unwired)

`formatForLLM(skipMediaDescription=)` (incl. the TEXT-guard trap §4.2);
`toModelMessage`/`toModelMessageList` `nativeImages=`;
`_loadNativeVisionImages` + `_makeDescriptionResolver`; StorageService import.

Tests (new, `tests/bot/models/test_ensured_message.py` or the existing ensured
message test home — mirror layout): construction happy path (all bytes →
`ModelImagesMessage`, no `mediaDescription` key in JSON / no TEXT prepend,
`storage.get` awaited-correctly, no `updateMediaContent` call); bytes-miss →
plain message with description AND the wait executed (mock-count the
`_awaitMedia` calls); partial album per the rule (attach subset + description
present + no resolver); ghost media does not block skip; never-raise on
DB/storage exceptions; default-`False` call sites byte-identical
(`skipMediaDescription` absent from the rendered JSON when False and media
described); resolver not invoked at construction; resolver at-most-once.

Acceptance: all existing chat tests unchanged and green (nothing passes
`nativeImages=True` yet).

### Phase C — eligibility helper, threading, deletion sweep

`_nativeVisionEnabled` (verbatim rule); thread the flag through all §4.7
sites incl. `getThreadByMessageForLLM`; gate the reply eager wait; delete
`_applyNativeVision`/`_getVisionUrl`/`_loadVisionBytes`/cap init/constant/
config key/`VisionConfigDict` entry; rewrite/extend/replace the test classes
per §6; keep the receipt-side suites untouched.

Tests (rewritten `TestNativeVisionChatAttach` → construction-attach through
the REAL entry points): handleReply fallback with fresh media + vision on →
images attached, eager wait skipped (mock `updateMediaContent` on the message
and assert not awaited when bytes load; awaited-once-inside-formatForLLM when
they don't); handleMention DB-parent album attaches; random window rows
attach AND the direct-condense path (:1129) receives image messages whose
resolvers the mocked condense consumes; randomContext summary contains the
resolved description; eligibility fail-soft (resolution error → descriptions);
vision-off → zero storage reads; media.py prompt-fallback unaffected (no
images in `latestMessages`).

Acceptance: grep-clean for `_applyNativeVision`, `_getVisionUrl`,
`_loadVisionBytes`, `DEFAULT_MAX_IMAGES_PER_REQUEST`,
`max-images-per-request`, `_maxImagesPerRequest`; `make test` green.

### Phase D — docs + CHANGELOG (docs-writer, `update-project-docs` skill)

Every item in §7, via markdown-mcp for the docs tree + plain tools for
CHANGELOG. ADR-028 insertion into `docs/llm/architecture.md` after ADR-027.

## 9. Open Questions

None blocking — the delegated micro-decisions are all resolved above
(§4.1–§4.9). Two explicit follow-ups owned by the user, restated for the
record:

1. **Cap re-add**: whether (and at what N / per-request vs per-message) to
   reintroduce an image cap after real-chat cost testing (ratified decision 2).
2. **`ModelImageMessage.descriptionResolver`**: deliberately not added
   (single-image parse path never skips descriptions); revisit only if a
   future consumer wants lazy descriptions on single-image messages.

## 10. References

- [`native-vision-design-v1.md`](native-vision-design-v1.md) — the v1 design
  this partially supersedes (§3.4/§3.5 chat-time mechanism; §3.6 matrix).
- [`docs/llm/architecture.md`](../llm/architecture.md) ADR-027 (:1167-1190) —
  implemented v1 decisions; receipt-side bullets remain authoritative.
- [`docs/llm/handlers.md`](../llm/handlers.md) §9 (:617) — current chat-time
  flow docs (rewritten in Phase D).
- [`docs/llm/services.md`](../llm/services.md) (:216) — condenser strip
  contract. [`docs/llm/libraries.md`](../llm/libraries.md) §1.3.
- Code entry points:
  [`internal/bot/models/ensured_message.py`](../../internal/bot/models/ensured_message.py),
  [`internal/bot/common/handlers/llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py),
  [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py),
  [`internal/services/llm/service.py`](../../internal/services/llm/service.py),
  [`internal/services/storage/service.py`](../../internal/services/storage/service.py),
  [`lib/ai/models.py`](../../lib/ai/models.py),
  [`internal/config/models.py`](../../internal/config/models.py),
  [`configs/00-defaults/vision.toml`](../../configs/00-defaults/vision.toml).
- [`.agents/skills/write-regression-test/SKILL.md`](../../.agents/skills/write-regression-test/SKILL.md)
  and [`.agents/skills/update-project-docs/SKILL.md`](../../.agents/skills/update-project-docs/SKILL.md)
  — the recipes Phases B–D follow.
