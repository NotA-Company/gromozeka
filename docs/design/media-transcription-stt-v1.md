# Design: Media Transcription (Speech-to-Text) v1

Status: **REVIEWED** — implementation-ready; release is gated by the smoke tests in §13.3  
Date: 2026-07-27  
Owner: TBD  
Companion docs: [`architecture.md`](../llm/architecture.md), [`services.md`](../llm/services.md), [`libraries.md`](../llm/libraries.md), [`configuration.md`](../llm/configuration.md), [`handlers.md`](../llm/handlers.md)

> This is a design document and implementation spec only. It does not add STT behavior.
> Implementation must use `software-developer`; the final documentation pass
> must load the `update-project-docs` skill. The product decisions in §2 were
> confirmed by the user on 2026-07-27.

## 1. Context and goal

Gromozeka stores inbound audio and video attachments but does not expose their
spoken content to the LLM. Add automatic Speech-to-Text for `VIDEO`,
`VIDEO_NOTE`, `VOICE`, and `AUDIO`, using Yandex SpeechKit v3 async recognition.

The transcript is stored in the existing `media_attachments.description`
column. The existing media refresh and formatting path then injects it into
LLM context as `mediaDescription` or `<media-description>` without a schema
migration ([`ensured_message.py:973-998`](../../internal/bot/models/ensured_message.py),
[`ensured_message.py:1063-1185`](../../internal/bot/models/ensured_message.py)).

The implementation must be safe under concurrent delivery, bound source and
decoded media before it can exhaust process memory, avoid duplicate billable
operations in the current single-process bot, and preserve existing image
processing behavior.

## 2. Ratified product decisions

| ID | Decision |
|---|---|
| D1 | Transcribe inbound `VIDEO`, `VIDEO_NOTE`, `VOICE`, and `AUDIO`. |
| D2 | Trigger automatically through a separate `TRANSCRIBE_MEDIA` chat setting. The setting is on the `FRIEND` page and defaults to `false`. |
| D3 | Use pinned PyAV for source-container decoding and audio normalization. |
| D4 | Persist formatted text in `media_attachments.description`; do not add a migration or transcript table in v1. |
| D5 | Introduce a provider-neutral `lib/stt/` abstraction and an internal singleton `STTService`. |
| D6 | Implement the Yandex wire protocol with raw `httpx`, not through an SDK wrapper. |
| D7 | Deliver timestamped transcript segments; the formatter uses the result-level attribution role: `[Speaker#<tag>] [start..end] text` for `SPEAKER`, `[Ch#<tag>]` only for multiple tags on `CHANNEL`, or an untagged timestamped line. Speaker labels are opaque and recording-local. |
| D8 | v1 started with inline SpeechKit input; v1.1 adds Yandex Object Storage routing for extracted clips at/above `max-inline-bytes` when configured. |

Review-derived constraints in this plan refine those decisions; they do not
change them.

## 3. Scope

### 3.1 Goals

1. Make spoken media available to the originating LLM turn when processing
   finishes within the existing media wait, and cache it for later turns.
2. Preserve utterance timestamps and provider-neutral word timestamps in
   memory while persisting only bounded formatted text.
3. Keep `lib/stt/` independent of bot and database modules.
4. Bound source bytes, decoded duration, decoded-buffer and inline-payload bytes, provider
   response bytes, transcript characters, admission time, and concurrency.
5. Make every started STT worker terminal when persistence is available:
   `DONE` with transcript, `DONE` with a no-speech sentinel, or `FAILED`.
   Gate-off media remains an intentional no-transcription `DONE` row.
6. Preserve current image parsing, attachment storage, and multi-platform
   formatting behavior.

### 3.2 Non-goals

- Object Storage input for files up to 1 GB / 4 hours.
- Stable speaker identity, cross-recording diarization, or support claims beyond
  the Yandex mono speaker-label response contract. Labels are opaque,
  recording-local, and Yandex documents at most two; they are not user identities.
- Automatic language detection; v1 uses a configured BCP-47 language.
- Multiple audio-track selection or mixing.
- Streaming/partial transcript delivery.
- A `/transcribe` command, direct transcript reply, or document export.
- Structured transcript persistence or search over transcript segments.
- Cross-process deduplication. The v1 claim mechanism is correct for the
  current single bot process, not a future multi-worker bot deployment.

## 4. Current state and corrections to the original draft

### 4.1 Media behavior today

The central path is
[`BaseBotHandler._processMediaV2`](../../internal/bot/common/handlers/base.py)
([`base.py:1726-1930`](../../internal/bot/common/handlers/base.py)). Important
existing semantics are:

- A cached `DONE` row returns before chat settings are read
  ([`base.py:1781-1785`](../../internal/bot/common/handlers/base.py)). This
  strands old audio rows that are `DONE` with no description unless the new
  branch deliberately reprocesses them.
- A fresh attachment becomes `DONE` when `PARSE_ATTACHMENTS=false`
  ([`base.py:1834-1841`](../../internal/bot/common/handlers/base.py)). It becomes
  `NEW` only when image parsing is enabled and detected MIME is not an image
  ([`base.py:1867-1901`](../../internal/bot/common/handlers/base.py)). Therefore,
  “all non-images are `NEW`” is not a valid baseline or test expectation.
- Existing nonterminal rows are reconsidered only when stored MIME starts with
  `image/`; a missing MIME is converted to the string `"None"`
  ([`base.py:1809-1819`](../../internal/bot/common/handlers/base.py)). STT
  eligibility must use platform `MessageType`, not stored MIME.
- A fresh `PENDING` row receives an empty task and is not reclaimed for 30
  minutes ([`base.py:1787-1804`](../../internal/bot/common/handlers/base.py),
  [`constants.py:104`](../../internal/bot/constants.py)). The new process-local
  task registry provides a stronger ownership signal for STT.

`MediaProcessingInfo.awaitResult()` directly awaits its attached task without
a timeout ([`media.py:39-51`](../../internal/bot/models/media.py)). Only the
subsequent database poll is bounded to 300 seconds
([`ensured_message.py:1011-1061`](../../internal/bot/models/ensured_message.py)).
STT must therefore return a completed dispatch task and let the existing DB
poll enforce the originating-turn bound; it must not attach the long-running
STT worker directly.

Message preprocessing can also wait for media before generating embeddings
([`message_preprocessor.py:134-209`](../../internal/bot/common/handlers/message_preprocessor.py)).
Latency affects preprocessing, not only the final chat response.

### 4.2 Download and concurrency behavior today

`TheBot.downloadAttachment` delegates Max downloads to `MaxBotClient` and
materializes Telegram downloads as a complete byte array
([`bot.py:1018-1040`](../../internal/bot/common/bot.py)). Max currently reads
the complete HTTP response with no streaming cap
([`client.py:1675-1723`](../../lib/max_bot/client.py)).

`QueueService.addBackgroundTask()` tracks tasks that are already running; it
is not an execution queue or concurrency guard
([`service.py:152-179`](../../internal/services/queue_service/service.py)).
Admission and the semaphore must therefore be owned by `STTService` and occur
before download and decode.

`BaseBotHandler.storeAttachment()` is declared async but performs MIME hashing,
`StorageService.exists()`, and `StorageService.store()` synchronously
([`base.py:1932-1967`](../../internal/bot/common/handlers/base.py)). The S3
backend calls synchronous boto3 `put_object()`
([`s3.py:113-135`](../../internal/services/storage/backends/s3.py)). Moving
storage under STT admission without offloading it would still block the entire
event loop.

### 4.3 Persistence and duplicate behavior today

`media_attachments.description` and the existing update repository are valid
targets ([`models.py:232-258`](../../internal/database/models.py),
[`media_attachments.py:180-295`](../../internal/database/repositories/media_attachments.py)).
No migration is required.

The current read-then-insert sequence can race. `addMediaAttachment()` catches
a duplicate insert and returns `False`, while the caller ignores the result
([`media_attachments.py:104-178`](../../internal/database/repositories/media_attachments.py)).
The implementation must check that return value, re-read the winner, and use a
process-local task registry keyed by `file_unique_id` before creating work.

### 4.4 Existing documentation drift

[`docs/database-schema-llm.md`](../database-schema-llm.md) currently describes
`media_attachments.metadata` with `DEFAULT ''`, while migration 013 declares
`metadata TEXT NOT NULL` without that default
([`migration_013:268-281`](../../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py)).
Code wins. Correct this drift during the implementation documentation pass;
do not copy it into new documentation.

## 5. Proposed architecture

### 5.1 Components

> **Superseded (2026-08-02 simplification):** The STTService is now stateless —
> no in-flight registry, no DB interaction. The handler owns the row lifecycle.
> See [`services.md`](../llm/services.md) and ADR-020.

```text
internal/bot/common/handlers/base.py
  - evaluates type and the chat gate
  - supplies declared size and invokes the existing platform download
  - preserves image/general-media behavior
                 |
                 v
internal/services/stt/STTService (singleton)
  - serialized per-media state/cache decision
  - keyed in-flight task registry
  - DB status transitions
  - rate/admission/concurrency controls
  - invokes loader, extraction, provider, formatter
                 |
                 v
lib/stt/audio.py
  - PyAV decode and limits
                 |
                 v
      YandexSpeechKitProvider
      - persistent httpx client
      - submit / poll / get / delete
      - co-located YandexObjectStorage helper (v1.1)
```

Proposed files:

```text
lib/stt/
  __init__.py
  abstract.py
  audio.py
  exceptions.py
  models.py
  providers/
    __init__.py
    yandex_speechkit.py
    yandex_object_storage.py     # v1.1: co-located Yandex Object Storage helper (boto3 hard import)
    yandex_events.py             # getRecognition streaming-JSON event parser

internal/services/stt/
  __init__.py
  service.py
  formatter.py                   # thin service-owned transcript formatter
```

`lib/stt/` must not import `internal.bot`, `internal.database`, or singleton
services. `STTService` is the integration boundary and may depend on the
database, rate limiter, queue-compatible tasks, and `lib/stt`.

### 5.2 End-to-end flow

```mermaid
sequenceDiagram
    participant H as _processMediaV2
    participant S as STTService
    participant B as TheBot (download)
    participant A as PyAV extractor
    participant Y as SpeechKit provider
    participant DB as media_attachments
    participant E as EnsuredMessage

    H->>H: Read settings; build typed request/loader
    H->>S: dispatchTranscription(request, chatGateEnabled)
    S->>DB: status=PENDING
    S-->>H: Worker reference after status-ready handshake
    H-->>E: MediaProcessingInfo with completed dispatch task
    S->>S: bounded rate/admission + semaphore
    S->>B: downloadAttachment(mediaId, fileId)
    B-->>S: source bytes (or None → DOWNLOAD_ERROR)
    S->>A: negotiate format + extract (pass-through/transcode; pass-through preserves channels, transcode converts)
    A-->>S: ExtractedAudio(data, durationMs)
    S->>Y: transcribe(format-aware ExtractedAudio)
    Y-->>S: FINAL / NO_SPEECH / ERROR
    alt FINAL
        S->>DB: status=DONE, description=bounded transcript
    else NO_SPEECH
        S->>DB: status=DONE, description=""
    else any failure
        S->>DB: status=FAILED
    end
    E->>DB: poll for at most MAX_MEDIA_AWAIT_SECS
```

`dispatchTranscription()` is called for every transcribable attachment,
including when the current gate is off, so it can join work that another chat
already started. It does not return from a started/joined path until a shared
readiness future confirms an observable `PENDING`/early terminal state, or a
safe persistence-abort result confirms that no provider call will occur. This
prevents the DB poll from observing the pre-worker `NEW` state and returning too
soon.
The completed dispatch task is intentional: it starts the existing 300-second
DB poll immediately and avoids the current unbounded direct wait. The real
worker remains registered with `QueueService` for graceful shutdown. If it
finishes after the originating poll, the transcript is still cached for later
messages; the worker must not be cancelled merely because that turn timed out.

## 6. Eligibility, cache, and state contract

### 6.1 Effective gate

New billable work requires all three activation gates:

```text
[stt].enabled
AND chatSettings[PARSE_ATTACHMENTS].toBool()
AND chatSettings[TRANSCRIBE_MEDIA].toBool()
```

The setting gates new work, not cache reads. A transcript already cached by
`file_unique_id` is reused in every chat that receives the same attachment,
even if the current chat setting is off. This matches the existing global
attachment-cache model and must be documented to operators.

Eligibility is based only on `MessageType in {VIDEO, VIDEO_NOTE, VOICE, AUDIO}`.
Stored or detected MIME is metadata, not an admission condition. PyAV validates
whether the bytes contain a decodable audio stream.

### 6.2 State decision table

> **Design pivot (2026-08-02):** There is no standalone `STTHandler`. The STT
> branch lives inside `BaseBotHandler._processMediaV2` in
> `internal/bot/common/handlers/base.py`. The timing is **background task**
> (like image parsing): `_processMediaV2` sets the row to `PENDING` via plain
> `updateMediaAttachment` (single attachments have no concurrent writes, so
> last-write semantics suffice — there is no CAS), schedules a background
> transcription task, and returns immediately. The LLM's `EnsuredMessage.updateMediaContent`
> awaits the task then confirms via the DB poll (~300 s) for the description.
> The background task persists the terminal transition (`DONE` or `FAILED`).
> This matches the existing image-parsing pattern and does not block the
> preprocessor.

`_processMediaV2` evaluates this table during its existing per-attachment
read/insert/update flow, before the legacy image-state early returns. Use a
bounded set of lock stripes (for example, 64 `asyncio.Lock` instances selected
by media ID) so the same ID is serialized without leaking per-ID locks; an
occasional collision only serializes brief DB state decisions.

| Existing state | Active registry task | Effective gate | Action |
|---|---:|---:|---|
| Unsupported `MessageType` | any | any | Follow the existing image/general path unchanged. |
| Any transcribable row | yes | either | Await the registry entry's status-ready future, create no duplicate worker, and return a completed dispatch task so the caller polls DB. |
| `DONE` row (with or without description) | no | either | Cache-hit / early-return: a `DONE` row always early-returns and is **never** re-transcribed, even if the gate has since flipped off→on. Reuse the existing description if present. |
| Missing row, `NEW`, or `FAILED` | no | off | Gate-off: ensure/normalize the row to `DONE` with no description; create no worker. |
| Orphaned `PENDING` | no | off | Gate-off: normalize to `DONE` with no description; create no worker. |
| Missing row, `NEW`, or `FAILED` | no | on | Claim: ensure the row exists, then set it to `PENDING` via `updateMediaAttachment`, and schedule a background transcription task. |
| Orphaned `PENDING` | no | on | Reclaim: re-stamp the row to `PENDING` via `updateMediaAttachment`, then schedule a background transcription task. |

For a missing row, insert it as `NEW`, then always re-read it. The current
`addMediaAttachment()` boolean conflates duplicate conflicts and operational
errors. Interpret `False + row exists` as a concurrent winner and reevaluate
the table; interpret `False + no row` as an operational failure and create no
worker. Treat `True + no observable row` the same safe way. Preserve the
existing media-type consistency check for a reused `file_unique_id`.

`updateMediaAttachment` is the terminalization helper used by
`_transcribeMedia`. Single attachments have no concurrent writes (one row per
`file_unique_id`, one in-flight task at a time), so plain last-write semantics
suffice — there is **no CAS** (the earlier `setStatusVerified` CAS design was
dropped when the design was simplified and the method was removed from the
repository). The background task writes the terminal transition directly.
Every exit after the provider call must be caught and persisted:

| Outcome | Status | Description |
|---|---|---|
| One or more non-empty final segments | `DONE` | Formatted from generic `attributionTag` plus the result role: `[Speaker#<tag>] [start..end] text` for `SPEAKER`, `[Ch#<tag>]` only for multiple tags on `CHANNEL`, or untagged. Equal timestamps render once. Speaker labels are opaque and recording-local. See [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py). |
| Valid recognition with no speech | `DONE` | `NO_SPEECH` returns `""` (no sentinel). See [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py). |
| Source too large, no audio track, corrupt media, download error, provider/operation/protocol error | `FAILED` | Remains null |

`FAILED` is retryable when a later message has the effective gate enabled.
v1 is user-silent: failures are operator-visible through bounded structured
logs, not a "clean error reply" to the user.

Terminal writes are update-plus-reread verified and use at most three attempts
with short bounded backoff for transient DB failures; they never resubmit to
SpeechKit within the same worker. If the terminal write still cannot be
observed, emit a critical log and end the registry task. A row left `PENDING`
then has no registry owner and is reclaimed by the next gate-enabled delivery.
The originating DB poll may time out during the outage; this is the explicit
recovery rule rather than a false guarantee that a terminal row can be written
while the DB is unavailable.

Update `EnsuredMessage._awaitMedia()` to treat expected `NEW` and `FAILED`
terminal rows explicitly rather than logging them as an invalid enum status.

### 6.3 In-process deduplication

> **Superseded (2026-08-02 simplification):** `dispatchTranscription()` and the
> `dict[str, STTInFlight]` in-flight registry are **removed**. `STTService` is
> stateless — deduplication is by the per-`file_unique_id` DB row (one row, one
> background task at a time). The handler owns the row lifecycle; see
> [`services.md`](../llm/services.md) and ADR-020.

`STTService` owns `dict[str, STTInFlight]`, keyed by media ID. Each internal
entry contains `task: asyncio.Task[None]` and a shared
`asyncio.Future[bool]`: `True` means an observable `PENDING`/terminal state;
`False` means persistence failed and processing safely aborted before provider
submission. Inside the media-ID lock stripe, `dispatchTranscription()` performs
lookup, optional `asyncio.create_task()`, and dictionary assignment without an
intervening `await`. Only the creator registers the worker with `QueueService`.
All callers then await the status-ready future through `asyncio.shield()` so
caller cancellation cannot cancel the shared signal. The worker completes that
future on every startup path.

The done callback removes the entry only when the dictionary still points to
that exact entry and task. This prevents an old callback from deleting a
replacement. The top-level worker catches all exceptions, checks repository
boolean results, attempts a terminal write, and never leaves an exception for
the task callback or caller to retrieve. A failed initial `PENDING` write or
verification prevents a provider call and emits a bounded critical log because
no implementation can guarantee a terminal row while the database itself is
unavailable.

This is not sufficient for multiple bot worker processes. Before such a
deployment, replace/reinforce it with a portable database compare-and-set claim
(owner token plus lease/expiry) and test cross-process takeover. The standalone
Max webhook receiver does not process media, so it does not violate the v1
assumption.

## 7. Models and interfaces

The provider-neutral model and exception surface lives in `lib/stt`:
`STTResultStatus` / `STTErrorCode` enums; the `TranscriptionWord`,
`TranscriptionSegment`, and `TranscriptionResult` records; the format-aware
`ExtractedAudio` (with `STTAudioContainerType` = `WAV`/`OGG_OPUS`/`MP3`); the
`AudioFormatSpec` negotiation descriptor; and the typed loader callable/result.
The load-bearing raise/return contract: providers never raise for expected
failures (they return `TranscriptionResult(ERROR, errorCode=...)`),
`audio.extractAudio()` is the only runtime raise-point inside `lib/stt` (typed
exceptions mapping 1:1 to `STTErrorCode`), and constructors may raise only on
startup config validation.

> **Authoritative contract:** [`lib-stt-v1.md` §4](./lib-stt-v1.md) — make changes there, not here. This section summarizes it only.

**`STTMediaRequest` (service-side integration boundary — **removed in the
2026-08-02 simplification**).** The internal `STTMediaRequest` carried
media/chat IDs, optional platform `declaredSize`, and a loader. The loader
result contained source `data`, actual `fileSize`, and optional detected
`mimeType`; the loader was an async typed callable that closed over platform
identifiers and the current `SAVE_ATTACHMENTS` behavior.
Download is performed by the existing unbounded `TheBot.downloadAttachment` (see
§12.4); size enforcement is post-download inside `STTService`.
`STTService` remains the final never-raise boundary for background work and maps
any unexpected exception to a terminal `FAILED` row.

## 8. Resource safety and audio extraction

### 8.1 Default product limits

Defaults deliberately stay below SpeechKit's vendor maximum:

| Guard | Default | Purpose |
|---|---:|---|
| Source container | 1,073,741,824 bytes (1 GiB; `max-source-bytes`) | Bound platform download and source buffer. User-configurable; currently defaults to 1 GiB per the accepted residual Max-unbounded-download risk (user decision 2026-08-03 — a large Max attachment fully materializes before `STTService` rejects it; Telegram is platform-capped ~20 MB by the bot API `getFile` limit). |
| Decoded buffer (`max-audio-bytes`) | (removed) | **Removed.** See [`lib-stt-v1.md` §5/§8.1](./lib-stt-v1.md). |
| Inline payload | 41,943,040 bytes (40 MiB; `max-inline-bytes`) | Bound `ExtractedAudio.data` (pass-through source or transcode output); base64-expanded must stay below the 60 MB vendor **inline** limit with headroom. |
| Decoded duration | (removed) | **Removed.** See [`lib-stt-v1.md` §5/§8.1](./lib-stt-v1.md). |
| Result body | 5,242,880 bytes (5 MiB) | Bound server-streamed event collection. |
| Persisted transcript | (removed) | **Removed.** See [`lib-stt-v1.md` §5/§8.1](./lib-stt-v1.md). |
| Global workers | 2 | Bound simultaneous download/decode/request memory. |
| Admission wait | (removed) | **Removed.** See [`lib-stt-v1.md` §5/§8.1](./lib-stt-v1.md). |
| HTTP request | 30 seconds | Bound each network request. |
| SpeechKit operation | 2400 seconds | Cap submit/poll/get for the SpeechKit operation itself. This is the full SpeechKit operation budget (`operation-budget-seconds`), not a media-poll budget; it sits well inside the 4 h vendor duration ceiling. |
| Poll interval | 2 seconds initially, 10 seconds maximum | Stay below operation polling quota. |

**Vendor ceilings vs. v1 defaults.** SpeechKit async ceilings: **60 MB inline request** (used by v1),
**1 GB Object-Storage upload** (deferred in v1 per D8), **4-hour duration** ceiling. v1 defaults stay
conservative on all three (§15 rejects vendor-max defaults as unsafe): the inline-payload cap keeps
base64-expanded requests under 60 MB, Object-Storage is unused, and the duration default stays far
below 4 h and is bounded by the 300 s media-poll.

All values are validated as positive and operator-configurable. The vendor ceiling is not a safe
application default. Release testing must measure peak RSS with two maximum-size workers; reduce the
source/duration/concurrency defaults if the deployment memory budget cannot absorb it.

### 8.2 Admission order

> **Superseded (2026-08-02 simplification):** The admitted-loader pipeline is
> **removed** — no `STTMediaRequest.declaredSize`, no 20-second admission
> budget, no service-side `PENDING` write. The handler writes `PENDING`,
> downloads synchronously, and passes bytes to the stateless
> `STTService.transcribeMedia(data, chatId=...)`; the service applies rate
> limits and the semaphore, and the handler persists the terminal row. See
> [`lib-stt-v1.md` §1](./lib-stt-v1.md) and ADR-020.

For a newly created worker:

1. Write `PENDING`.
2. Reject a known `STTMediaRequest.declaredSize` over the cap (**removed in the
   2026-08-02 simplification**).
3. Within the 20-second admission budget, apply the per-chat limiter, apply the
   global vendor limiter, and acquire the global semaphore.
4. Under the semaphore, perform the unbounded platform download via the
   existing `TheBot.downloadAttachment`; `None` → `FAILED` +
   `DOWNLOAD_ERROR`. On success, `STTService.transcribeMedia` enforces the
   source-byte cap post-download. Then perform optional storage, MIME
   detection, PyAV extraction, provider submission, and result mapping.
5. Persist a terminal state and release the semaphore.

The current rate limiter sleeps rather than rejects
([`manager.py:303-325`](../../lib/rate_limiter/manager.py)). The explicit
admission timeout is what creates a terminal timeout result. Applying two
blocking limiters can conservatively consume one permit if the subsequent
wait times out; this reduces throughput but cannot exceed a quota.

### 8.3 Platform download (simplified, 2026-08-03)

> **Design simplification (2026-08-03):** The earlier bounded-download platform
> extension (`downloadAttachment(mediaId, fileId, maxBytes=…)`) is **dropped**.
> STT uses the **existing unbounded** `TheBot.downloadAttachment(mediaId, fileId)
> -> Optional[bytes]`. See §12.4 for the full model.

For transcribable types, move download, optional `storeAttachment`, MIME
detection, and their DB metadata updates into the admitted loader. Do not
download once for storage before the semaphore and again for STT. MIME remains
informational; PyAV decides whether audio is valid.

Refactor attachment storage so the complete MIME/hash/exists/store sequence is
a synchronous private helper invoked through `asyncio.to_thread()`; do not call
the current synchronous storage backend methods on the event loop. Preserve
existing best-effort semantics: if `SAVE_ATTACHMENTS` storage fails after its
backend retries/timeouts, log a bounded error, leave `localUrl` unset, and
continue transcription with the downloaded bytes.

Give S3 finite backend-level network behavior by adding validated connect/read
timeouts and total retry-attempts to `[storage.s3]` and passing them through
`botocore.config.Config`. Proposed defaults are 10 seconds connect timeout, 60
seconds socket read timeout, and two total attempts. These are transport bounds,
not a fake hard deadline around `to_thread()`; cancellation cannot stop an
already-running filesystem/boto call. The worker keeps its semaphore slot until
the storage helper returns, so source-memory and concurrency bounds still hold,
and §8.4's shutdown limitation applies.

### 8.4 PyAV contract

> **Superseded (2026-08-02 simplification):** `extractAudio()` no longer enforces
> caps — `DurationExceededError` and the stop-at-cap / reject-on-pass-through
> duration logic are **removed**. Negotiation is container-only; the handler /
> service bound source bytes and duration before calling `extractAudio`. See
> [`lib-stt-v1.md` §5](./lib-stt-v1.md).

Pin `av==18.0.0` (supported wheels bundle FFmpeg libraries on published macOS /
manylinux / musllinux artifacts; source builds still require FFmpeg development
libraries — do not claim system FFmpeg is never needed on unsupported platforms).
`extractAudio()` is PyAV-based: it probes the source, then takes exactly one
negotiated path — **pass-through** (source container already in the provider's
`supportedInputFormats`, payload within the inline-payload cap), **transcode**
(unsupported container, or supported-but-over-cap, encoded to the provider's
first compressed format), or **reject**. The channel policy is: pass-through
preserves source channels; transcode clamps channels to the target spec's
`[minChannels, maxChannels]` range (downmix/upmix via `AudioResampler`) and the
output rate to `[minSampleRate, maxSampleRate]` (nearest bound). Duration is
measured from the actual sample count; a
pass-through source over the duration cap is rejected with
`DurationExceededError` (compressed audio cannot be truncated without a re-encode),
while the transcode path stops at the cap. The old single "20 MiB WAV" bound
splits into a channel-aware **decoded-buffer cap** (`max-audio-bytes`) and an
**inline-payload cap** (`max-inline-bytes`, base64-expanded must stay below the
60 MB vendor inline limit). Extraction runs via `asyncio.to_thread()`; native
decoding is not stoppable by coroutine cancellation, so source/sample/output and
concurrency caps are the real resource controls, and v1 drains STT workers
gracefully without an in-process hard shutdown deadline (a native hang can delay
shutdown indefinitely; deployment supervision may impose an external hard-kill).
The PyAV import is unconditional (no guarded import — simplification trade-off); any
`import lib.stt.*` hard-requires PyAV at import time.

> **Authoritative contract:** [`lib-stt-v1.md` §5](./lib-stt-v1.md) — make changes there, not here. This section summarizes it only.

## 9. Yandex SpeechKit v3 provider contract

The Yandex provider speaks the async v3 REST API over raw `httpx` using
**protobuf-JSON, not gRPC**: `POST recognizeFileAsync` to submit,
`GET operations/{id}` to poll, `GET getRecognition` to fetch streaming
recognition events, and a best-effort `DELETE deleteRecognition` to reduce
result retention — all authenticated with `Authorization: Api-Key` and
`x-folder-id`. The `container_audio.container_audio_type` field is set
dynamically from `ExtractedAudio.container` (one of `WAV`/`OGG_OPUS`/`MP3`). The
retry policy is load-bearing: **never auto-retry the submit `POST`** (a timeout
can occur after Yandex has accepted a billable operation); the idempotent
poll/fetch `GET`s retry 429/5xx with bounded backoff inside the 2400-second
operation budget, and each `getRecognition` attempt is atomic (no segments
committed from a partial stream). Gate-1 is **VERIFIED/PASS**: committed
aurumentation fixtures record the live `getRecognition` streaming-JSON framing
with its top-level `result` wrapper. Bare-envelope parsing remains defensive
compatibility for variant or future input, not a release blocker. The proxy is
**injected** as an already-resolved `ProxyConfig` — never resolved inside
`lib/stt` (resolving it there would bypass per-service proxy lifecycle
registration). `yandex-ai-studio-sdk` is a credible fallback, but D6 keeps raw
`httpx` for explicit wire/streaming/caps/retry/proxy/cleanup control.

`[stt].force-mono` defaults to `false` and is provider-owned. When enabled, Yandex
advertises mono-only descriptors, which forces otherwise compatible multi-channel
audio through downmix/re-encode while retaining supported mono pass-through. The
option is lossy and can change routing based on the extracted payload. Regardless
of this option, a final mono `ExtractedAudio` causes both inline and Object Storage
submissions to request Yandex speaker labeling. The parser stores a canonical envelope
tag as generic `attributionTag` and marks the result role as `SPEAKER` for that request;
deprecated final-level tags are ignored. See the authoritative [`lib-stt-v1.md` §4/§7](./lib-stt-v1.md).

> **Authoritative contract:** [`lib-stt-v1.md` §7](./lib-stt-v1.md) — make changes there, not here. This section summarizes it only.

## 10. Transcript formatting and trust boundary

The pure service formatter,
[`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py),
turns non-empty segments into one plain-text line each, retaining their supplied
order. Its exact output is `[Speaker#<tag>] [start..end] text` for a non-empty
generic `attributionTag` on a `SPEAKER` result; `[Ch#<tag>]` appears only for a
`CHANNEL` result with multiple distinct non-empty tags, or the line is untagged.
Equal start/end uses one timestamp. Speaker labels are opaque and recording-local.
The formatter strips/skips empty text, returns `""` when no segment remains, and
does not alter text or impose a transcript-length cap.

The handler persists that result in `media_attachments.description`. The existing
rendering path delivers it to the LLM as structured JSON `mediaDescription` data
for the default `LLM_MESSAGE_FORMAT = "smart"` user-message format; multi-media
messages carry one description per attachment. The transcript is never made a
system-role message. See the library-internals authority,
[`lib-stt-v1.md` §6](./lib-stt-v1.md), for the formatter contract.

## 11. Configuration and lifecycle

### 11.1 Proposed defaults

Add `configs/00-defaults/stt.toml`:

```toml
[stt]
enabled = false
provider = "yandex-speechkit"
use-proxy = false
# Opt-in: constrain Yandex input descriptors to mono; multi-channel compatible
# input is downmixed/re-encoded, while compatible mono input stays pass-through.
force-mono = false
max-concurrency = 2
chat-ratelimiter-queue = "stt-chat"
global-ratelimiter-queue = "stt-global"

max-source-bytes = 1073741824  # 1 GiB (user decision 2026-08-03; see §8.1)

api-key = "${YC_API_KEY}"
folder-id = "${YC_FOLDER_ID}"
model = "general"
language = "ru-RU"
request-timeout-seconds = 30
operation-budget-seconds = 2400
poll-interval-seconds = 2
max-poll-interval-seconds = 10
max-result-bytes = 5242880

# v1.1 — gate-3 routing threshold: clips whose extracted form (len(audio.data))
# is at/above this route to Object Storage (when configured); else inline.
max-inline-bytes = 41943040

# v1.1 — gate-3 Object Storage (Yandex Object Storage, S3-compatible).
# Implicitly enabled when object-storage-bucket is set together with both keys.
#object-storage-bucket = "stt-clips"
#object-storage-prefix = "stt/"
#object-storage-key-id = "${YC_STT_S3_KEY_ID}"
#object-storage-key-secret = "${YC_STT_S3_SECRET_KEY}"

# **Deleted keys (2026-08-02 simplification):** `max-audio-bytes`,
# `max-duration-seconds`, `max-transcript-chars`, `admission-timeout` — see
# `configs/00-defaults/stt.toml` for the current keys.
```

Extend the existing `[storage.s3]` table in
`configs/00-defaults/storage.toml` and wire the values into the boto3 client:

```toml
connect-timeout-seconds = 10
read-timeout-seconds = 60
total-max-attempts = 2
```

Add explicit limiter definitions and mappings to
`configs/00-defaults/00-config.toml` rather than silently using `default`.
Insert the definitions before the file's existing `[ratelimiter.queues]`
section:

```toml
[ratelimiter.ratelimiters.stt-chat]
type = "SlidingWindow"

[ratelimiter.ratelimiters.stt-chat.config]
windowSeconds = 3600
maxRequests = 20

[ratelimiter.ratelimiters.stt-global]
type = "SlidingWindow"

[ratelimiter.ratelimiters.stt-global.config]
windowSeconds = 3600
maxRequests = 450
```

Then add these keys inside the existing `[ratelimiter.queues]` table; do not
declare that TOML table a second time:

```toml
stt-chat = "stt-chat"
stt-global = "stt-global"
```

The service applies `stt-chat` with `key=str(chatId)` and `stt-global` with its
queue-level key. The defaults are conservative policy values and remain
operator-configurable.

Add `transcribe-media = false` under `[bot.defaults]` and add
`ChatSettingsKey.TRANSCRIBE_MEDIA = "transcribe-media"` plus its complete
`_chatSettingsInfo` entry on `ChatSettingsPage.FRIEND`. Consumer code must use
`chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()`, not DB-layer tuple
indexing ([`chat_settings.py:287-376`](../../internal/bot/models/chat_settings.py),
[`chat_settings.py:626`](../../internal/bot/models/chat_settings.py),
[`chat_settings.py:867-873`](../../internal/bot/models/chat_settings.py)).

### 11.2 Validation

`ConfigManager` gains a typed STT accessor. When `enabled=false`, do not
instantiate the provider, load PyAV, or validate credentials. When enabled,
fail startup for:

- missing/empty provider, API key, or folder ID;
- unresolved `${...}` placeholders (environment substitution deliberately
  leaves them unchanged when absent);
- unknown provider type;
- invalid/non-positive limits, delays, or concurrency;
- missing PyAV;
- missing rate-limiter queue mappings.

Use `YC_API_KEY` and `YC_FOLDER_ID`, already used by existing Yandex provider
configuration. Do not add or print secrets.

### 11.3 Startup and shutdown

In [`main.py:71-100`](../../main.py), initialize STT after `ProxyService` and
after rate-limiter configuration, but before constructing the bot application:

1. Read typed STT config.
2. Initialize the singleton service with config and database.
3. If enabled, resolve the `stt` proxy and construct the configured provider directly.
4. If disabled, leave the manager absent and the service reporting disabled.

On shutdown, the queue must drain STT workers before closing their HTTP client.
Then close the configured provider through `STTService.aclose()`, destroy rate limiters, close other managers,
and finally close the database. Preserve the existing proxy lifecycle ordering
([`main.py:121-155`](../../main.py)). Add an import/startup regression test to
catch circular imports.

## 12. Handler integration contract

> **Design pivot (2026-08-02):** There is **no standalone `STTHandler`**. The
> STT branch is an extension of `BaseBotHandler._processMediaV2` in
> `internal/bot/common/handlers/base.py`. The earlier framing of a separate
> handler class is superseded. No new handler registration is needed, and the
> "register before `LLMMessageHandler`" invariant is **moot** — `_processMediaV2`
> is already invoked from `MessagePreprocessorHandler.newMessageHandler`, which
> is registered FIRST/SEQUENTIAL before `LLMMessageHandler`.

### 12.1 Location and gating

The STT branch lives inside `_processMediaV2` (`base.py`), between the existing
status decision logic and the DB write. For each attachment, the branch
evaluates:

```text
transcribeMedia = sttEnabled (cached at handler init as _sttEnabled)
               AND mediaType ∈ {VIDEO, VIDEO_NOTE, VOICE, AUDIO}
               AND chatSettings[ChatSettingsKey.PARSE_ATTACHMENTS].toBool()
               AND chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()
```

`PARSE_ATTACHMENTS` is the general attachment-processing gate (it gates any
attachment processing in `_processMediaV2`, not just image parsing);
`TRANSCRIBE_MEDIA` is the additional opt-in for the expensive STT sub-feature.
All four gates default to off. When the effective gate is off, transcribable
attachments are terminalized to `DONE` without description (gate-off in §6.2).
When on, the branch proceeds to the row-lifecycle logic.

### 12.2 Row lifecycle in _processMediaV2

The branch fits into `_processMediaV2`'s existing read/insert/update flow:

- **Cache-hit**: existing `DONE` row → reuse immediately, no new work. A `DONE`
  row **always** early-returns and is never re-transcribed, even if it has no
  description and the gate has since flipped off→on.
- **Gate-off**: gate is off → normalize to `DONE` with no description, no-op.
- **Claim**: `NEW`, `FAILED`, or orphaned `PENDING` → set to `PENDING` via
  `updateMediaAttachment`, then schedule a background transcription task.
- **Background task persists**: the scheduled `_transcribeMedia(mediaId, chatId, data)`
  task calls `STTService.transcribeMedia(data, chatId=...)` and writes the
  terminal transition (`DONE`+description or `FAILED`) to the DB via
  `updateMediaAttachment`. It does **not** download — the bytes are downloaded
  synchronously inside `_processMediaV2` (shared download block) and passed in
  as `data`.
- **Terminalize every path**: the background task catches every `Exception` and
  writes a terminal state; `asyncio.CancelledError` propagates (it is a
  `BaseException`, not caught by `except Exception`) and leaves the row
  `PENDING` for the orphan-reclaim path on a later delivery.

`updateMediaAttachment` is the terminalization helper — plain last-write
semantics. Single attachments have no concurrent writes (one row per
`file_unique_id`, one in-flight task at a time), so there is **no CAS** (the
former `setStatusVerified` CAS helper was removed when the design was
simplified).

### 12.3 Background-task scheduling

`_processMediaV2` sets `MediaProcessingInfo.task` to the live STT background
task (`ret.task = sttTask`) for STT — **mirroring the image-parsing pattern**
(`ret.task = parseTask`). `updateMediaContent()` awaits the task and then
confirms via its bounded DB poll (~300 s); the end-to-end wait is equivalent
either way, so consistency with image parsing is preferred. The preprocessor
returns immediately and the LLM's media poll observes the `PENDING` row until
the background task writes `DONE` or `FAILED`. If the poll times out, the
transcript is still cached for later messages.

> **Mirrors image parsing (2026-08-03):** image parsing sets
> `ret.task = parseTask` and the LLM awaits the parse task directly. STT does
> the same — `ret.task = sttTask`. The earlier "uncapped await" concern is
> retired: `updateMediaContent` awaits the STT task **and** confirms via the DB
> poll, so the wait is bounded by the poll cap either way.

### 12.4 Download (simplified, 2026-08-03)

> **Design simplification (2026-08-03):** The bounded-download platform
> extension (`downloadAttachment(mediaId, fileId, maxBytes=…)`) described in
> earlier drafts is **dropped**. STT uses the **existing unbounded**
> `TheBot.downloadAttachment(mediaId, fileId) -> Optional[bytes]` — no new
> method, no `maxBytes` parameter.

The download is **synchronous inside `_processMediaV2`** (the shared download
block), so the bytes are fetched exactly once when both `SAVE_ATTACHMENTS` and
the STT branch need them. `_transcribeMedia(self, mediaId, chatId, data)`
receives the already-downloaded `data` as a positional argument and does **NOT**
download itself. Two outcomes from the synchronous download:

- **`None`** (download failure) → terminalize via `updateMediaAttachment` to
  `FAILED` (`STTErrorCode.DOWNLOAD_ERROR`).
- **`data: bytes`** → passed through to the background `_transcribeMedia` task,
  which calls `STTService.transcribeMedia(data, chatId=…)`.

`STTService.transcribeMedia` enforces the source-byte cap **post-download**:
`len(data) > max-source-bytes` → `SOURCE_TOO_LARGE` (this check already exists
in `STTService`; it is not new). `SOURCE_SIZE_UNKNOWN` is **never produced**
by this path (no pre-download size check is performed); it remains a reserved
value in the `STTErrorCode` enum.

**Accepted residual risk:** the Max download is unbounded into memory — a large
Max attachment is fully materialized before `STTService` rejects it. Telegram
is inherently platform-capped (~20 MB, the bot API `getFile` limit). The
`max-source-bytes` default remains **1 GiB** (`configs/00-defaults/stt.toml`,
user decision 2026-08-03).

### 12.5 Transcript delivery to the LLM

The transcript is written to `media_attachments.description` by the background
task. The existing media refresh and formatting path delivers it to the LLM as
a structured JSON `mediaDescription` field — the **same mechanism used for
image descriptions today**. When the default `LLM_MESSAGE_FORMAT = "smart"`
format renders user messages as JSON, the transcript (in
`media_attachments.description`) appears as a top-level `mediaDescription` key
in the structured user message. This provides strong structural isolation for
prompt-injection mitigation (see §10). No separate text header or XML-escape
wrapper is needed for the LLM delivery path.

Multi-attachment rendering dissolves naturally: each attachment gets its own
row and its own `mediaDescription` list entry.

### 12.6 Existing behavior preserved

Telegram and Max routing already pass all four selected `MessageType`s through
`_processMediaV2` ([`base.py:1507-1724`](../../internal/bot/common/handlers/base.py)).
Max multi-attachment uses `setMediaId=False`; test per-item `media.content`
injection rather than only the primary `mediaContent` field. Image parsing
and unsupported-media behavior remain unchanged.

## 13. Implementation plan and verification

### 13.1 Incremental implementation

| Step | Work | Verification before continuing |
|---:|---|---|
| 1 | Pin `av==18.0.0` under `# Runtime` in `requirements.direct.txt`; reconcile direct dependencies and regenerate the frozen lock. | Install on supported macOS and Alpine/musllinux CI; verify through a test module, never `python -c`. |
| 2 | Add provider-neutral models, errors, and PyAV extractor; keep transcript rendering in the service formatter. | Focused model/audio tests, including limits and resource cleanup. |
| 3 | Add `AbstractSTTProvider`, exact Yandex provider, and golden fixtures. | Mock-transport provider suite; no real network in automated tests. |
| 4 | Add typed config, STT defaults, two limiter mappings, proxy injection, singleton service, lifecycle, admission, and registry. | Config/service/main lifecycle tests; singleton isolation. |
| 5 | Add attachment storage offload and finite S3 transport/retry settings while preserving uncapped callers and best-effort storage semantics. (The bounded-download platform extension was dropped 2026-08-03; STT uses the existing unbounded `downloadAttachment`.) | Platform/storage adapter tests with declared, missing, lying, streamed, delayed, and failed backends. |
| 6 | Refactor `_processMediaV2`, add chat setting, expected terminal handling, and auto-injection tests. | Real-DB state/race tests plus unchanged-image regression tests. |
| 7 | Run manual SpeechKit and resource/latency smoke tests from §13.3. | Record redacted request/result shapes and measured latency/RSS. |
| 8 | Update all docs in §14, add the changelog entry, and run the complete quality gates. | `make check-docs`, `make format lint`, `make test`, and `make ci`. |

Dependency workflow must follow repository rules: edit
`requirements.direct.txt`, use `make install-direct` in the reconciled venv,
run `make freeze-requirements`, then verify a locked/clean installation. Do not
edit `requirements.txt` by hand.

### 13.2 Automated test matrix

All new tests live under `tests/` mirroring source paths, except sanctioned
vendored-package tests. Async tests need no explicit asyncio decorator.

**lib/stt slice (models, PyAV extraction, Yandex golden HTTP).** The model,
extraction/multi-format negotiation, parser, provider, and golden-replay suites
are specified in full in the library test matrix. They cover canonical
envelope-level attribution coercion, ignored deprecated-final tags, refinement
retention, and `PROTOCOL_ERROR` for malformed cursor/index or other protocol
structures; detailed parser rules remain authoritative in
[`lib-stt-v1.md` §7](./lib-stt-v1.md). They also cover forced-mono
downmix/pass-through and speaker-label request/parse semantics. Two sanitized
live golden recordings require `FINAL`, non-empty segments, generic
attribution-tag set `{"0", "1"}`, and result role `SPEAKER` so a dropped final or
attribution regression cannot pass as `NO_SPEECH`. Service tests assert exact
role-sensitive speaker/channel/untagged and equal-timestamp formatted output
plus structured description delivery. See [`lib-stt-v1.md` §9](./lib-stt-v1.md).

> **Authoritative contract:** [`lib-stt-v1.md` §9](./lib-stt-v1.md) — make changes there, not here. This section summarizes it only.

**Service and concurrency**

- Declared oversize fails before limiter/loader; loader runs only after both
  rate limits and semaphore admission.
- Per-chat throttling, global throttling, admission timeout, and concurrency 2.
- Every non-persistence exception produces verified terminal `FAILED` when the
  DB is writable, and no task exception leaks; persistence failures follow the
  safe-abort/orphan-reclaim contract in §6.
- Concurrent first-seen duplicates call the loader/provider once.
- Active duplicate reuses registry task; identity-safe callback cleanup;
  orphaned `PENDING` reclaim; the dispatch call cannot return before
  `PENDING`/early-terminal persistence is observable or a verified safe abort
  prevents the provider call.
- `addMediaAttachment()` false with and without an observable winner; a
  nominally successful status update that matches no observable row; terminal
  write retry exhaustion. Assert no provider call when `PENDING` cannot be
  verified.
- Singleton reset in shared fixtures, including STT manager/service and any
  rate/queue state used by these tests.

**Handler/database integration**

- Each of `VIDEO`, `VIDEO_NOTE`, `VOICE`, and `AUDIO`.
- Global/chat disabled normalization, cached transcript reuse while disabled,
  `DONE` without description reprocessing, `NEW`/`FAILED` retry, active
  `PENDING` reuse, orphan reclaim, success, no speech, and failure.
- Insert-conflict reread and concurrent first insert with provider-called-once.
- Download/storage/MIME failure becomes verified `FAILED` when the DB is
  writable; mocked terminal-write failure follows the documented orphan
  recovery instead of claiming an impossible guarantee. (The bounded-download
  platform extension was dropped 2026-08-03; download uses the existing
  unbounded `downloadAttachment`.)
- `PARSE_ATTACHMENTS=false` and `true` legacy behavior remains correct for
  unsupported types; image parsing remains unchanged.
- Telegram and Max download behavior (unbounded `downloadAttachment`; the
  bounded-download extension was dropped 2026-08-03).
- A delayed synchronous storage backend runs off-loop (verify with an unrelated
  event-loop heartbeat); S3 timeout/retry config is passed to botocore; optional
  storage failure leaves `localUrl` unset but does not suppress transcription.
- JSON and TEXT transcript injection, primary media, and Max
  multi-attachment/per-item injection.

**Startup/lifecycle**

- Disabled STT does not require credentials/provider/PyAV.
- Enabled unresolved credentials and invalid limits fail startup.
- Resolved proxy is injected; persistent client closes after queue drain.
- Import/startup has no cycle.

### 13.3 Manual release gates

These require credentials or platform/runtime behavior and cannot be proven by
static review:

- **gate-1 — live-wire `getRecognition` framing.** ✅ PASS (2026-08-02).
  `_resolveEnvelope` in `lib/stt/providers/yandex_events.py` correctly matches
  the real Yandex SpeechKit v3 framing in both aurumentation fixtures. No code
  changes. Coverage-gap caveat: clean TTS single-utterance clips don't exercise
  multi-chunk / `NO_SPEECH` / `ERROR` / bare-envelope / missing-`finalRefinement`
  branches — dedicated fixtures needed before release.
- **gate-2 — model confirmation.** Confirm `general` vs `deferred-general` is the
  appropriate production model for this workload; retain the configured model
  either way.
- **gate-3 — inline-limit semantics.** Confirm the provider's inline limit (60 MB
  inline vs base64 expansion). The product stays at the conservative 40 MiB
  inline-payload default regardless.
- **gate-4 — 10-min end-to-end latency.** Test representative 10-minute media
  end to end. If p95 processing exceeds the existing 300-second media poll,
  reduce default duration or redesign originating-turn waiting — **never**
  attach an unbounded worker task.
- **gate-5 — RSS / decoded-memory budget.** Measure peak RSS and CPU with two
  max-size (1 GiB) source files and worst-case decoded output on
  deployment-equivalent hardware. Tied to the accepted decoded-memory gap:
  `lib/stt` does NOT bound decoded PCM; the service bounds source bytes
  (`max-source-bytes`, currently 1 GiB) and the `_processMediaV2` branch bounds
  duration before the provider decodes. **If gate-5 fails, revisit restoring a
  decoded-buffer cap inside `lib/stt`'s decode path.**
- **gate-6 — graceful shutdown.** Exercise graceful shutdown during a
  maximum-size decode; verify the deployment supervisor's external hard-kill
  grace policy for a simulated native hang.
- **gate-7 — `make ci` Alpine-wheel proof.** Run `make ci` to prove the pinned
  PyAV wheel works in the Alpine container.
- **gate-8 — PyAV encoder availability.** `libopus` / `libmp3lame` present in
  the `av==18.0.0` wheel on every target platform. *(Already verified present.)*
- **gate-9 — quality-by-format (UNVERIFIED).** One clip recognized pass-through
  (OGG_OPUS) and transcoded, compared. Proven win is size/traffic, not quality.

Plus SpeechKit auth smoke + end-to-end smoke — run one short real recognition
and capture only redacted structural output to confirm submit, operation, event
framing, refinement ordering, and delete.

No secrets, full audio, full transcripts, or authorization headers may be
stored in smoke-test artifacts.

## 14. Documentation impact

After implementation, load `update-project-docs` and update:

- `docs/llm/architecture.md`: add the next available ADR (currently ADR-020;
  recheck at implementation time) for provider boundary, cache semantics,
  keyed single-process claim, and bounded admission.
- `docs/llm/services.md`: `STTService`, dependencies, task registry, lifecycle.
- `docs/llm/libraries.md`: `lib/stt`, PyAV, provider wire contract.
- `docs/llm/configuration.md`: `[stt]`, credentials, limits, proxy, limiter
  queues, and `TRANSCRIBE_MEDIA`.
- `docs/llm/handlers.md`: revised media state flow and catch-all ordering check.
- `docs/llm/database.md`: semantic use of `description` and global cache; no
  schema change.
- `docs/llm/testing.md`: STT fixtures/golden tests/singleton resets.
- `docs/llm/index.md`: add the new service/library links and recompute any
  aggregate counts from the live file; do not hardcode a stale singleton count.
- `docs/developer-guide.md` and `README.md` where user/operator setup belongs.
- `AGENTS.md` only if the compact architecture/config gotchas warrant an entry.
- `docs/database-schema.md` and `docs/database-schema-llm.md`: keep the pair in
  sync on the new `description` semantics and correct the pre-existing
  `metadata`-default drift noted in §4.4.
- `CHANGELOG.md`: one user-visible `Added` entry under `Unreleased`.

This plan-only rewrite does not itself require a changelog entry.

## 15. Alternatives and trade-offs

| Alternative | Decision |
|---|---|
| Reuse `PARSE_ATTACHMENTS` | Rejected by D2. STT has a distinct cost and trust profile. |
| Persist a transcript table/JSON | Deferred. `description` already feeds both output formats; structured persistence would require schema and retention policy. |
| Use the existing Yandex AI Studio SDK | Credible fallback, but D6 keeps raw `httpx` for exact streaming, caps, retry, proxy, and delete control. |
| Shell out to `ffmpeg` | Rejected by D3. Pinned PyAV gives an in-process API and supported binary wheels, with source-build caveats. |
| Run download/decode before service admission | Rejected. It permits CPU/memory storms before the semaphore. |
| Rely on `QueueService` for concurrency | Rejected. It tracks tasks after creation and does not delay execution. |
| Attach the STT worker to `MediaProcessingInfo` | Rejected. `awaitResult()` is unbounded before the 300-second DB poll. |
| Database claim in v1 | Deferred for simplicity under the current single-process bot. Mandatory before multi-worker bot deployment. |
| Decode in a killable subprocess | Deferred. It provides a hard shutdown/CPU deadline but adds IPC and worker lifecycle complexity; required if v1's bounded-input in-process risk is unacceptable. |
| Use the full 60 MB inline / 1 GB Object-Storage / 4-hour vendor limits | Rejected as unsafe defaults because source, decoded audio, base64, JSON, and provider results create multiple memory copies and long user-path latency. (Object-Storage is also deferred in v1 per D8.) |

## 16. Acceptance criteria

Implementation is complete only when:

1. All four media types transcribe through one bounded pipeline when all three activation gates
   are on, and cached descriptions reuse without new cost.
2. State transitions match §6 under disabled gates, duplicates, orphaned
   pending rows, no speech, and every failure stage.
3. Concurrent first delivery of one media ID creates exactly one provider call
   in the current single bot process.
4. No source download, decode, or provider request occurs before admission;
   all configured byte/duration/concurrency caps are enforced.
5. Yandex requests and event parsing match §9, submit is not blindly retried,
   and successful results are deleted best-effort.
6. Persisted transcripts retain timestamp ranges and optional generic
   attribution tags, with role-sensitive speaker/channel/untagged formatting,
   and are injected through the structured `mediaDescription` path for single
   and multi-media messages. Parser internals remain authoritative in
   [`lib-stt-v1.md` §7](./lib-stt-v1.md).
7. Disabled STT starts without credential/provider validation; enabled invalid
   config fails fast; shutdown drains workers and closes clients in order.
8. Existing image and unsupported-media behavior has regression coverage and
   remains unchanged.
9. Manual latency, memory, live-wire, and Alpine-wheel gates in §13.3 pass.
10. Documentation in §14 is synchronized and all project quality gates pass.
