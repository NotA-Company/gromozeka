# STT Feature — Next Steps (Handler Round)

> **ARCHIVED (2026-08-08):** the roadmap tracked here is fully IMPLEMENTED —
> `lib/stt` v1 + `STTService` + the `_processMediaV2` handler round + the v1.1
> gate-3/gate-4 code are all done; only manual smoke testing + operator-enable
> prerequisites remain. Retained as historical record — the live authoritative
> docs are [`docs/design/stt-v1.1.md`](../design/stt-v1.1.md),
> [`docs/design/media-transcription-stt-v1.md`](../design/media-transcription-stt-v1.md),
> and [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md).

> **UPDATE (2026-08-03): the handler round is IMPLEMENTED.** STT is now wired
> into `BaseBotHandler._processMediaV2` (the `_processMediaV2` STT branch +
> the `_transcribeMedia` background task in
> [`internal/bot/common/handlers/base.py`](../../../internal/bot/common/handlers/base.py)),
> gated by `[stt].enabled` config + the per-chat `PARSE_ATTACHMENTS` and
> `TRANSCRIBE_MEDIA` settings (all default `false`), with 16 tests in
> `tests/bot/common/handlers/test_base.py::TestProcessMediaV2STT`. All §2
> checklist items are checked off below. §3 (manual release gates) is unchanged
> — most gates remain pending (only gate-1 is PASS); STT stays default-off
> until an operator turns both gates on.
>
> **UPDATE (2026-08-08): v1.1 (gate-3 + gate-4) is IMPLEMENTED.** Object-Storage
> routing (`lib/stt/providers/yandex_object_storage.py`, `_transcribe` lifecycle,
> `max-inline-bytes` config) and per-transcription statistics recording
> (template-method refactor: `_recordStats` + timing in base
> `AbstractSTTProvider.transcribe`) are fully implemented and green (3726 passed /
> 11 skipped / 0 failed). Gate-3 and gate-4 code is DONE; their smoke-test parts
> remain open. See [`stt-v1.1.md`](../design/stt-v1.1.md).

> **Start here.** `lib/stt` (provider-neutral STT library), `STTService`
> (stateless singleton), and the `TRANSCRIBE_MEDIA` chat setting (4 of 4
> sites DONE) are all implemented, green, and **committed** on branch
> `add-audio-transcribation-v2` (user's `eb4827e` STTService-simplify commit
> + the A1/A2/A3 code/test catch-up + the aurumentation/doc work + the
> `TRANSCRIBE_MEDIA` addition). All green: ~3662 tests, `make lint` 0/0/0,
> `make check-docs` 0 broken.
>
> **The next step is the handler round** — wire the feature into the bot so
> it becomes user-visible (still default-off). **PIVOT (2026-08-02): there is
> NO standalone `STTHandler`.** STT folds into `BaseBotHandler._processMediaV2`
> ([`internal/bot/common/handlers/base.py`](../../../internal/bot/common/handlers/base.py))
> — the per-attachment media method that `MessagePreprocessorHandler.newMessageHandler`
> delegates to via `processTelegramMedia`/`processMaxMedia`. The preprocessor is
> registered FIRST/SEQUENTIAL before `LLMMessageHandler`, so extending
> `_processMediaV2` is sufficient — no new handler registration is needed and
> the `LLMMessageHandler`-stays-last invariant is no longer a concern.
>
> **Key files to load first:**
> - [`internal/bot/common/handlers/base.py`](../../../internal/bot/common/handlers/base.py) — `_processMediaV2` is the method to extend; the STT branch lives here (gated on TRANSCRIBE_MEDIA + `[stt].enabled`, filtered to VIDEO/VIDEO_NOTE/VOICE/AUDIO, background-task timing like image parsing).
> - [`internal/services/stt/service.py`](../../../internal/services/stt/service.py) — the stateless `STTService.transcribeMedia(data: bytes, *, chatId: Optional[int]) -> STTOutcome` entry the background task will call.
> - [`internal/bot/models/chat_settings.py`](../../../internal/bot/models/chat_settings.py) — `ChatSettingsKey.TRANSCRIBE_MEDIA` (line 393) + `_chatSettingsInfo` entry (line 924, BOOL / `ChatSettingsPage.FRIEND`). Already defined — the `_processMediaV2` STT branch only READS it.
> - [`lib/stt/`](../../../lib/stt/) — provider-neutral library; see [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) for contracts.
> - [`internal/services/stt/formatter.py`](../../../internal/services/stt/formatter.py) — the THIN formatter (`[HH:MM:SS.mmm] text` only; no header/escape/truncate/sentinel). Prompt-injection mitigation was deliberately shed here — and is no longer needed at this layer (see §2 RESOLVED below).
> - [`internal/database/repositories/media_attachments.py`](../../../internal/database/repositories/media_attachments.py) — row terminalization is via `MediaAttachmentsRepository.updateMediaAttachment` (plain update, no CAS; single attachments have no concurrent writes); the `_processMediaV2` STT branch owns the row lifecycle.
> - [`internal/bot/common/handlers/llm_messages.py`](../../../internal/bot/common/handlers/llm_messages.py) — `LLMMessageHandler`'s JSON `mediaDescription` delivery path: default `LLM_MESSAGE_FORMAT = "smart"` renders user messages as JSON; `media_attachments.description` reaches the model as a structured top-level `mediaDescription` key (same mechanism already used for image descriptions).
> - [`tests/lib/stt/golden/`](../../../tests/lib/stt/golden/) — aurumentation golden suite with RECORDED TTS-generated fixtures (see [`docs/llm/aurumentation.md`](../../llm/aurumentation.md)).
> - [ADR-020](../../llm/architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall) — the stateless-service + dependency-firewall decision.
> - Reference docs: the [parent plan](../design/media-transcription-stt-v1.md) (product decisions D1–D8, §6 state machine, §11 config, §12 handler contract, §13.3 manual gates) and the [lib/stt spec](../design/lib-stt-v1.md) (library contracts, §6 formatter-moved-out, §10(b) gates).

---

## 1. Current state (the launchpad)

- **`lib/stt/`** — provider-neutral Speech-to-Text library: implemented, lint-clean, test-green, default-off everywhere. `AbstractSTTProvider.stt(data: bytes, *, consumerId: Optional[str] = None) -> TranscriptionResult` is the never-raise extract+transcribe entry; `transcribe(audio, *, consumerId=None)` is the concrete template-method on the base (wraps the abstract `_transcribe(audio)` with timing, `_recordStats`, and the never-raise exception boundary). `STTErrorCode` has **9 values** with documented ownership:
  - **Service-produced:** `STT_DISABLED`, `SOURCE_TOO_LARGE`. (`PROVIDER_ERROR` is also produced by the service as the defense-in-depth catch-all.)
  - **Provider-produced** (returned inside `TranscriptionResult(ERROR, ...)`): `NO_AUDIO`, `PROVIDER_ERROR`, `PROTOCOL_ERROR`, `OBJECT_STORAGE_ERROR` (v1.1 — Object Storage upload failure).
  - **Provider-produced (extended v1.1):** `SOURCE_TOO_LARGE` is also surfaced by the Yandex provider when the extracted payload exceeds `maxInlineBytes` and Object Storage is disabled.
  - **Reserved for the handler** (not currently produced): `DURATION_EXCEEDED`.
  - **Produced by the handler** (download path): `DOWNLOAD_ERROR` (`downloadAttachment` returns `None`).
- **`STTService`** ([`internal/services/stt/service.py`](../../../internal/services/stt/service.py)) — STATELESS singleton; `async transcribeMedia(data: bytes, *, chatId: Optional[int]) -> STTOutcome`. Thin never-raise pipeline: `STT_DISABLED` → `SOURCE_TOO_LARGE` (when `len(data) > maxSourceBytes`) → per-chat/global rate limiters → `async with self._semaphore` (NO timeout) → `await provider.stt(data, consumerId=str(chatId))` → `_mapOutcome` (FINAL/NO_SPEECH → `DONE` + `formatTranscript`; ERROR → `FAILED` + provider `errorCode`) → return. Only `asyncio.CancelledError` propagates. Config `[stt]` in [`configs/00-defaults/stt.toml`](../../../configs/00-defaults/stt.toml) (default `enabled = false`; `${YC_API_KEY}`/`${YC_FOLDER_ID}`). Validation lives in the provider (`YandexSpeechKitProvider.__init__`). Lifecycle wired into [`main.py`](../../../main.py). v1.1 additions: `STTService.initialize(configManager, *, statsStorage=...)` accepts optional `StatsStorage` (gated on `[stats].enabled` in `main.py`); the flat `[stt]` Object-Storage keys are spread to the provider via `kebabToCamelCase`. Design recorded in [ADR-020](../../llm/architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall).
- **`TRANSCRIBE_MEDIA` chat setting — DEFINED (4 of 4 sites DONE):**
  - [x] Site 1 — `ChatSettingsKey.TRANSCRIBE_MEDIA = "transcribe-media"` ([`chat_settings.py:393`](../../../internal/bot/models/chat_settings.py)).
  - [x] Site 2 — `_chatSettingsInfo` entry: BOOL / `ChatSettingsPage.FRIEND` ([`chat_settings.py:924`](../../../internal/bot/models/chat_settings.py)).
  - [x] Site 3 — default `transcribe-media = false` under `[bot.defaults]` ([`configs/00-defaults/bot-defaults.toml:92`](../../../configs/00-defaults/bot-defaults.toml)).
  - [x] **Site 4 (consumer)** — the `_processMediaV2` STT branch reads `chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()` ([`base.py:1851`](../../../internal/bot/common/handlers/base.py)).
- **Row lifecycle helper** ([`media_attachments.py`](../../../internal/database/repositories/media_attachments.py)) — the `_processMediaV2` STT branch owns the row lifecycle via `MediaAttachmentsRepository.updateMediaAttachment` (plain last-write update; single attachments have no concurrent writes, so there is no CAS — the earlier `setStatusVerified` CAS design was dropped when the design was simplified and the method was removed from the repository).
- **Aurumentation golden suite** ([`tests/lib/stt/golden/`](../../../tests/lib/stt/golden/)) — TTS-generated example fixtures committed (`yandex_basic_transcription_ru.json`, `yandex_english_transcription_en.json`); see [`docs/llm/aurumentation.md`](../../llm/aurumentation.md). Used for gate-1 (below).
- **Branch / commit state:** branch `add-audio-transcribation-v2`; user's `eb4827e` STTService-simplify commit + the catch-up + aurumentation/doc work + the `TRANSCRIBE_MEDIA` addition are all **committed**. Handler round starts from a clean base.

---

## 2. Handler round checklist

Each item is a checkbox + a one-line scope + the relevant skill / load-bearing note.

**PIVOT (2026-08-02):** There is NO standalone `STTHandler`. STT folds into
`BaseBotHandler._processMediaV2` — the per-attachment media method the
preprocessor delegates to. No new handler registration; the
`LLMMessageHandler`-stays-last invariant is no longer a concern.

- [x] **`_processMediaV2` STT branch** in [`internal/bot/common/handlers/base.py`](../../../internal/bot/common/handlers/base.py) — extend the per-attachment media method that `MessagePreprocessorHandler.newMessageHandler` delegates to via `processTelegramMedia`/`processMaxMedia`. Gated on `chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()` **and** `chatSettings[ChatSettingsKey.PARSE_ATTACHMENTS].toBool()` **and** config `[stt].enabled` (cached at handler init as `_sttEnabled`, like `_searchEnabled`). Filtered to `mediaType ∈ {VIDEO, VIDEO_NOTE, VOICE, AUDIO}`. **Timing = background task** (like image parsing): `_processMediaV2` claims the row to PENDING, schedules a background transcription task, returns immediately; the LLM's `EnsuredMessage.updateMediaContent` polls the DB (~300s) for the description. Does NOT block the SEQUENTIAL/FIRST preprocessor. No new handler registration needed. (Parent plan §12.) **DONE (2026-08-03):** the STT branch lives at [`base.py:1845`](../../../internal/bot/common/handlers/base.py) (`sttEligible` + `sttGateOn`), schedules `_transcribeMedia` via `queueService.addBackgroundTask` + sets `ret.task = sttTask` (mirrors image parsing's `ret.task = parseTask`; `updateMediaContent` awaits the task then confirms via the bounded DB poll).

- [x] **Own the FULL `media_attachments` row lifecycle** — owned by the `_processMediaV2` STT branch and its background task:
  - **read / cache-hit:** a row already at `DONE` (with or without a description) → always early-return, never re-transcribe;
  - **gate-off:** a row at `DONE` with no description → no-op;
  - **claim / orphan-reclaim to `PENDING`:** `NEW` or orphaned `PENDING` → `PENDING` via `updateMediaAttachment` (plain update; single attachments have no concurrent writes, so no CAS);
  - **background task persists:** `updateMediaAttachment` to `DONE` with `description=formatTranscript(...)` on success, or `updateMediaAttachment` to `FAILED` with `description=None` on failure;
  - **terminalize** every path — orphan-reclaim handles task cancellation.
  - Reference: parent plan [§6 state machine](../design/media-transcription-stt-v1.md). (The earlier `setStatusVerified` CAS design was dropped when the design was simplified and the method was removed from the repository.)

- [x] **Download via existing `downloadAttachment` (synchronous in `_processMediaV2`; bounded variant dropped 2026-08-03).** ~~**Bounded `downloadAttachment(maxBytes=…)` platform extension**~~ — the bounded-download platform extension (socket-level byte cap, `SOURCE_SIZE_UNKNOWN` outcome) was **dropped** (user decision 2026-08-03). The download is **synchronous inside `_processMediaV2`** (shared download block — single download when both `SAVE_ATTACHMENTS` and STT need the bytes), using the **existing unbounded** `TheBot.downloadAttachment(mediaId, fileId) -> Optional[bytes]`: `None` → terminalize via `updateMediaAttachment` to `FAILED` + `DOWNLOAD_ERROR`; bytes → passed positionally to `_transcribeMedia(mediaId, chatId, data)`, which does **NOT** download (it calls `STTService.transcribeMedia(data, chatId=…)`, which enforces `SOURCE_TOO_LARGE` post-download). `SOURCE_SIZE_UNKNOWN` is never produced (reserved). (Per the accepted decoded-memory gap: source bytes are bounded BEFORE the provider decodes.) **DONE (2026-08-03):** `_processMediaV2` performs the synchronous download; `_transcribeMedia` ([`base.py:1384`](../../../internal/bot/common/handlers/base.py)) receives `data` positionally and does NOT download; download failure → `updateMediaAttachment(..., target=FAILED)` + `DOWNLOAD_ERROR` log.

- [x] **Prompt-injection mitigation — RESOLVED (2026-08-02).** Not needed as a text header / XML-escape / untrusted-data label. The transcript reaches the LLM as a structured JSON `mediaDescription` field (strong structural isolation) — the SAME mechanism already used to deliver image descriptions today. Default `LLM_MESSAGE_FORMAT = "smart"` renders user messages as JSON; the transcript (in `media_attachments.description`) reaches the model as a structured top-level `mediaDescription` key. The `<media-description>` TEXT tags only apply to assistant messages or chats explicitly set to `text` format. **This fully honors the injection-mitigation goal without any per-transcript header wrapping.** (Parent plan §6.1 / §12 — OPEN DESIGN ITEM closed.)

- [x] **Multi-attachment TEXT rendering — DISSOLVED (2026-08-02).** Each attachment has its own `media_attachments` row → its own `mediaDescription` list entry in the JSON. No stitching / recomputation needed. The original concern is moot.

- [x] **`CHANGELOG.md` `Added` entry + handler docs** — the user-visible feature ships with the `_processMediaV2` extension. Add one `Added` entry under `## [Unreleased]` in [`CHANGELOG.md`](../../../CHANGELOG.md) (see [`docs/llm/changelog.md`](../../llm/changelog.md) for format); update [`docs/llm/handlers.md`](../../llm/handlers.md) — note the standalone-`STTHandler` framing in those docs is superseded by the `_processMediaV2` extension; run the [`README.md`](../../../README.md) staleness check (parent plan §14). Load the [`update-project-docs`](../../../.agents/skills/update-project-docs/SKILL.md) skill for the full pass. **DONE (2026-08-03):** `CHANGELOG.md` `Added` entry added (line 10); [`docs/llm/handlers.md`](../../llm/handlers.md) `MessagePreprocessorHandler` row updated with the `_processMediaV2` STT-branch description.

- [ ] **Per-deployment friend-tier enable** — `transcribe-media = true` under `[bot.tier-defaults.friend]` in the **gitignored** `configs/common/01-bot-defaults.toml`. NOTE: this file is gitignored, so it is a **manual per-deployment step, NOT a commit** — document it in the handler docs, do not stage it. **(Operator step — remains pending per deployment; not a code task.)**

- [x] **Regression tests for the `_processMediaV2` STT branch** — load the [`write-regression-test`](../../../.agents/skills/write-regression-test/SKILL.md) skill. Cover at least: gate-off no-op, cache-hit reuse, persist `DONE`/`FAILED`, terminalization on every error code. Reset `STTService._instance = None` in fixtures (singleton). **DONE (2026-08-03):** 16 tests in [`tests/bot/common/handlers/test_base.py::TestProcessMediaV2STT`](../../../tests/bot/common/handlers/test_base.py) covering gate-off (config + chat-setting), cache-hit reuse, NEW→DONE per media type, download-returns-None → FAILED, service FAILED → FAILED, transcribe raises → FAILED, `ret.task` set to the live STT task, bot-None → FAILED, orphaned-PENDING reclaim. *(DONE-without-description reprocessing and CAS-loses-race-no-crash tests were removed in the simplification: DONE rows now always early-return, and CAS was dropped along with `setStatusVerified`, so the corresponding test was deleted.)*

---

## 3. Manual release gates (block ENABLING, not code completion)

These are manual/operational gates that must pass before STT is **enabled in production**. Per [parent §13.3](../design/media-transcription-stt-v1.md) + [lib/stt spec §10(b)](../design/lib-stt-v1.md), automated `lib/stt` + integration can be code-complete **and default-off** while these remain open — STT ships behind `[stt].enabled = false` + per-chat `TRANSCRIBE_MEDIA` (both off by default), so green code does not enable any billable behavior until an operator turns it on.

Carried forward (the two most actionable called out, then the rest):

- [x] **gate-1 — live-wire `getRecognition` framing. PASS (2026-08-02).** Code-analyst verified `_resolveEnvelope` in [`lib/stt/providers/yandex_events.py`](../../../lib/stt/providers/yandex_events.py) correctly matches the real Yandex SpeechKit v3 framing in BOTH aurumentation fixtures ([`tests/lib/stt/golden/data/yandex_basic_transcription_ru.json`](../../../tests/lib/stt/golden/data/yandex_basic_transcription_ru.json), [`yandex_english_transcription_en.json`](../../../tests/lib/stt/golden/data/yandex_english_transcription_en.json)). Real shape = TWO newline-separated JSON objects each wrapped in `{"result": {...}}`: (1) `final` with raw alternatives, (2) `finalRefinement` with `finalIndex` + `normalizedText`; timestamps are STRINGS handled by `_coerceInt`. NO code changes. **Coverage-gap caveat:** fixtures are clean TTS single-utterance clips, so multi-chunk / NO_SPEECH / ERROR / bare-envelope / missing-finalRefinement branches remain unexercised (de-riskable later by recording more aurumentation scenarios with live API). **Optional follow-up:** flip the `_resolveEnvelope` docstring PROVISIONAL→VERIFIED (trivial).

- [ ] **gate-5 — RSS / decoded-memory budget.** Tied to the accepted decoded-memory gap (§4): `lib/stt` does NOT bound decoded PCM memory; the service bounds source bytes + the `_processMediaV2` branch bounds duration BEFORE the provider decodes. Measure the real spike under those caps. **If gate-5 fails, revisit restoring a decoded-buffer cap INSIDE `lib/stt` (the one cap that can only live in the decode path).**

- [ ] **gate-2** — model confirmation (`general` vs `deferred-general` for this workload).
- [ ] **gate-3** — inline-limit semantics. **Code DONE (v1.1, 2026-08-08):** Object-Storage routing implemented (`lib/stt/providers/yandex_object_storage.py` + `_transcribe` lifecycle in `yandex_speechkit.py`; `max-inline-bytes` config key; `OBJECT_STORAGE_ERROR` + extended `SOURCE_TOO_LARGE`). **Smoke open:** confirm 60 MB inline vs base64 expansion, exact URI scheme, `container_audio_type` on `uri` path (see [`stt-v1.1.md`](../design/stt-v1.1.md) §11). Product stays at the conservative 40 MiB default regardless.
- [ ] **gate-4** — 10-min end-to-end latency. **Code DONE (v1.1, 2026-08-08):** per-transcription stats recording in `AbstractSTTProvider.transcribe` (template-method: `_recordStats` + timing in base, hoisted from the Yandex provider). `audio_duration_ms` vs `elapsed_time` enables the latency correlation. Stats gated on `[stats].enabled` (global, via `main.py`). **Smoke open:** measure p95 `elapsed_time` for representative 10-minute media and decide whether duration default or originating-turn wait needs adjustment.
- [ ] **gate-6** — graceful shutdown during a max-size decode; verify the deployment supervisor's external hard-kill grace policy for a simulated native hang.
- [ ] **gate-7** — `make ci` Alpine-wheel proof (pinned PyAV wheel works in the Alpine container).
- [ ] **gate-8** — PyAV encoder availability (`libopus` / `libmp3lame` present in the `av==18.0.0` wheel on every target platform). *(Already verified present.)*
- [ ] **gate-9** — quality-by-format (UNVERIFIED): one clip recognized pass-through (OGG_OPUS) and transcoded, compared. Proven win is size/traffic, not quality.

Plus SpeechKit auth smoke + end-to-end smoke — see parent §13.3 for the full operational list. No secrets, full audio, full transcripts, or authorization headers may be stored in smoke-test artifacts.

> **gate-3 / gate-4 code: IMPLEMENTED.** [`docs/design/stt-v1.1.md`](../design/stt-v1.1.md) designs the code behind gate-3 (Object-Storage routing for clips over the inline threshold) and gate-4 (per-transcription statistics recording in `lib/stt`). **Both are fully implemented** (2026-08-08). The manual confirmation / smoke parts of both gates remain open; gates 2/5/6/7/8/9 need no v1.1 code.

---

## 4. Open design notes / deferred nits

- **Prompt-injection mitigation placement — RESOLVED (2026-08-02).** Transcript reaches the LLM as a structured JSON `mediaDescription` field (strong structural isolation; same mechanism as image descriptions). No untrusted-data header / XML-escape / truncation needed at the formatter or handler level. See §2 checklist item.

- **Accepted decoded-memory gap.** `lib/stt` does not bound decoded PCM; `STTService` bounds source bytes (`max-source-bytes`, post-download) and the `_processMediaV2` STT branch bounds duration BEFORE calling `stt()`. Revisit (restore a decoded-buffer cap inside `lib/stt`'s decode path) **if gate-5 fails**. Documented in the `extractAudio` docstring + [`lib-stt-v1.md`](../design/lib-stt-v1.md).

- **`**extraKwargs` config-typo-swallow in `YandexSpeechKitProvider.__init__`** ([`yandex_speechkit.py:162`](../../../lib/stt/providers/yandex_speechkit.py)) — the constructor accepts arbitrary kwargs, so a misspelled `[stt]` key (e.g. `folde-id`) is silently swallowed instead of raising at startup. A deferred nit — could filter explicitly against the known key set, or drop `**extraKwargs` and let unexpected keys raise. Not blocking.

- **`transcribe-media` enum↔TOML-key invariant is intentionally NOT covered by a dedicated test (accepted trade-off).** The dedicated `TRANSCRIBE_MEDIA` unit tests (existence + enum↔TOML-key invariant) were deliberately deleted as low-value — the setting is exercised end-to-end by its `_processMediaV2` STT branch consumer (`chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()`), which surfaces any wiring drift at handler time. This is an accepted trade-off (no dedicated drift-guard test), not a gap to fill.

- **Committed launchpad.** Everything above (lib/stt simplified + STTService stateless + `TRANSCRIBE_MEDIA` 3-of-4 sites + aurumentation/doc work) is **committed** on `add-audio-transcribation-v2`. Handler round starts from a clean base.

- **§7.2 delete-ordering (load-bearing, do not "fix").** The provider runs its best-effort `DELETE` in `finally` (before parse) — an intentional refinement of "after fetch and parse". Documented in [lib/stt spec §7.2](../design/lib-stt-v1.md) + a load-bearing code comment.

---

*Sibling design docs (`../design/`): [parent plan](../design/media-transcription-stt-v1.md), [lib/stt spec](../design/lib-stt-v1.md).*
