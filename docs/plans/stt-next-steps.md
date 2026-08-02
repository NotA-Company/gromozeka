# STT Feature — Next Steps (Handler Round)

> **Start here.** `lib/stt` (provider-neutral STT library), `STTService`
> (stateless singleton), and the `TRANSCRIBE_MEDIA` chat setting (3 of 4
> sites DONE) are all implemented + green and living **uncommitted** on the
> working tree of branch `add-audio-transcribation-v2` (user's `eb4827e`
> STTService-simplify commit + the A1/A2/A3 code/test catch-up + the
> aurumentation/doc work + the `TRANSCRIBE_MEDIA` addition). All green:
> ~3662 tests, `make lint` 0/0/0, `make check-docs` 0 broken.
>
> **The next step is the handler round** — wire the feature into the bot so
> it becomes user-visible (still default-off). This doc is the actionable
> checklist for that round.
>
> **Key files to load first:**
> - [`internal/services/stt/service.py`](../../internal/services/stt/service.py) — the stateless `STTService.transcribeMedia(data: bytes, *, chatId: Optional[int]) -> STTOutcome` entry the handler will call.
> - [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py) — `ChatSettingsKey.TRANSCRIBE_MEDIA` (line 393) + `_chatSettingsInfo` entry (line 924, BOOL / `ChatSettingsPage.FRIEND`). Already defined — the handler only READS it.
> - [`lib/stt/`](../../lib/stt/) — provider-neutral library; see [`docs/plans/lib-stt-v1.md`](lib-stt-v1.md) for contracts.
> - [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py) — the THIN formatter (`[HH:MM:SS.mmm] text` only; no header/escape/truncate/sentinel). Prompt-injection mitigation was deliberately shed here.
> - [`internal/database/repositories/media_attachments.py`](../../internal/database/repositories/media_attachments.py) — `setStatusVerified(mediaId, *, expected, target, description=None)` atomic CAS (line 297); the handler owns the row lifecycle.
> - [`tests/lib/stt/golden/`](../../tests/lib/stt/golden/) — aurumentation golden suite with RECORDED TTS-generated fixtures (see [`docs/llm/aurumentation.md`](../llm/aurumentation.md)).
> - [ADR-020](../llm/architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall) — the stateless-service + dependency-firewall decision.
> - Reference docs: the [parent plan](media-transcription-stt-v1.md) (product decisions D1–D8, §6 state machine, §11 config, §12 handler contract, §13.3 manual gates) and the [lib/stt spec](lib-stt-v1.md) (library contracts, §6 formatter-moved-out, §10(b) gates).

---

## 1. Current state (the launchpad)

- **`lib/stt/`** — provider-neutral Speech-to-Text library: implemented, lint-clean, test-green, default-off everywhere. `AbstractSTTProvider.stt(data: bytes) -> TranscriptionResult` is the never-raise extract+transcribe entry. `STTErrorCode` has **8 values** with documented ownership:
  - **Service-produced:** `STT_DISABLED`, `SOURCE_TOO_LARGE`. (`PROVIDER_ERROR` is also produced by the service as the defense-in-depth catch-all.)
  - **Provider-produced** (returned inside `TranscriptionResult(ERROR, …)`): `NO_AUDIO`, `PROVIDER_ERROR`, `PROTOCOL_ERROR`.
  - **Reserved for the handler** (not currently produced): `SOURCE_SIZE_UNKNOWN`, `DOWNLOAD_ERROR`, `DURATION_EXCEEDED`.
- **`STTService`** ([`internal/services/stt/service.py`](../../internal/services/stt/service.py)) — STATELESS singleton; `async transcribeMedia(data: bytes, *, chatId: Optional[int]) -> STTOutcome`. Thin never-raise pipeline: `STT_DISABLED` → `SOURCE_TOO_LARGE` (when `len(data) > maxSourceBytes`) → per-chat/global rate limiters → `async with self._semaphore` (NO timeout) → `await provider.stt(data)` → `_mapOutcome` (FINAL/NO_SPEECH → `DONE` + `formatTranscript`; ERROR → `FAILED` + provider `errorCode`) → return. Only `asyncio.CancelledError` propagates. Config `[stt]` in [`configs/00-defaults/stt.toml`](../../configs/00-defaults/stt.toml) (default `enabled = false`; `${YC_API_KEY}`/`${YC_FOLDER_ID}`). Validation lives in the provider (`YandexSpeechKitProvider.__init__`). Lifecycle wired into [`main.py`](../../main.py). Design recorded in [ADR-020](../llm/architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall).
- **`TRANSCRIBE_MEDIA` chat setting — DEFINED (3 of 4 sites DONE):**
  - [x] Site 1 — `ChatSettingsKey.TRANSCRIBE_MEDIA = "transcribe-media"` ([`chat_settings.py:393`](../../internal/bot/models/chat_settings.py)).
  - [x] Site 2 — `_chatSettingsInfo` entry: BOOL / `ChatSettingsPage.FRIEND` ([`chat_settings.py:924`](../../internal/bot/models/chat_settings.py)).
  - [x] Site 3 — default `transcribe-media = false` under `[bot.defaults]` ([`configs/00-defaults/bot-defaults.toml:92`](../../configs/00-defaults/bot-defaults.toml)).
  - [ ] **Site 4 (consumer) is the ONLY remaining setting site** — the handler reads `chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()`. (See handler checklist below.)
- **`setStatusVerified`** ([`media_attachments.py:297`](../../internal/database/repositories/media_attachments.py)) — `setStatusVerified(mediaId, *, expected, target, description=None)` exists + is unit-tested (true atomic CAS via `UPDATE … WHERE file_unique_id = :id AND status = :expected RETURNING <all columns>`). `STTService` does NOT use it (stateless) — it is ready for the HANDLER to own the row lifecycle.
- **Aurumentation golden suite** ([`tests/lib/stt/golden/`](../../tests/lib/stt/golden/)) — TTS-generated example fixtures committed (`yandex_basic_transcription_ru.json`, `yandex_english_transcription_en.json`); see [`docs/llm/aurumentation.md`](../llm/aurumentation.md). Actionable for gate-1 (below).
- **Branch / commit state:** branch `add-audio-transcribation-v2`; user's `eb4827e` STTService-simplify commit + the catch-up + aurumentation/doc work + the `TRANSCRIBE_MEDIA` addition are all **uncommitted in the working tree**. Review/commit before or during the handler round (see §4).

---

## 2. Handler round checklist

Each item is a checkbox + a one-line scope + the relevant skill / load-bearing note.

- [ ] **`STTHandler`** in `internal/bot/common/handlers/` — friend-gated on `TRANSCRIBE_MEDIA` (the setting is ALREADY defined across sites 1–3 — just READ it: `chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()`) **and** config-gated on `[stt].enabled`. **Must be registered BEFORE `LLMMessageHandler`** (the catch-all invariant). **Load the [`add-handler`](../../.agents/skills/add-handler/SKILL.md) skill** when this lands. (Parent plan §12.)

- [ ] **Own the FULL `media_attachments` row lifecycle** (the stateless service shed ALL of this — the handler re-owns it):
  - **read / cache-hit:** a row already at `DONE` with a description → reuse, do NOT re-transcribe;
  - **claim / orphan-reclaim to `PENDING`** via `setStatusVerified(mediaId, expected=NEW_or_PENDING, target=PENDING)` (the atomic CAS already exists + is unit-tested);
  - **persist the `STTOutcome`:** `setStatusVerified(mediaId, expected=PENDING, target=DONE, description=formatTranscript(...))` on success, or `setStatusVerified(mediaId, expected=PENDING, target=FAILED, description=None)` on failure;
  - **terminalize** every path — never leave a row stranded in `PENDING`.
  - Reference: parent plan [§6 state machine](media-transcription-stt-v1.md) + the existing [`setStatusVerified` CAS](../../internal/database/repositories/media_attachments.py).

- [ ] **Bounded `downloadAttachment(maxBytes=…)` platform extension** — the handler downloads the media, bounds it by `[stt].max-source-bytes`, and passes the resulting `data: bytes` to `transcribeMedia(data, chatId=…)`. Promote the bound into a `maxBytes=` arg on the platform download path so the limit is enforced at the socket, not after the full body is buffered. Emits `SOURCE_SIZE_UNKNOWN` (download returned no size) / `DOWNLOAD_ERROR` (download raised) — both codes are reserved for the handler on the enum. (Per the accepted decoded-memory gap: source bytes are bounded BEFORE the provider decodes.)

- [ ] **Prompt-injection mitigation — OPEN DESIGN ITEM (must be decided this round).** The thin formatter ([`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py)) deliberately dropped the untrusted-data header / XML-escape / truncation (see ADR-020 decision 7 + [`lib-stt-v1.md`](lib-stt-v1.md) §6). **Before any transcript reaches an LLM prompt, an untrusted-content label MUST be re-added.** Decide WHERE this round: handler wraps the transcript string? a shared prompt-builder helper? restore the header in the formatter? Flag this prominently — it is a security-relevant decision, not a cosmetic one. (Parent plan §6.1 / §12.)

- [ ] **Multi-attachment TEXT rendering reuses the already-computed multi-attachment content** (readiness correction #3) — do not recompute and lose Max per-item descriptions when stitching the transcript into the message TEXT.

- [ ] **`CHANGELOG.md` `Added` entry + handler docs** — the user-visible feature ships with the handler. Add one `Added` entry under `## [Unreleased]` in [`CHANGELOG.md`](../../CHANGELOG.md) (see [`docs/llm/changelog.md`](../llm/changelog.md) for format); add the `STTHandler` row to [`docs/llm/handlers.md`](../llm/handlers.md); run the [`README.md`](../../README.md) staleness check (parent plan §14). Load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill for the full pass.

- [ ] **Per-deployment friend-tier enable** — `transcribe-media = true` under `[bot.tier-defaults.friend]` in the **gitignored** `configs/common/01-bot-defaults.toml`. NOTE: this file is gitignored, so it is a **manual per-deployment step, NOT a commit** — document it in the handler docs, do not stage it.

- [ ] **Regression tests for the handler** — load the [`write-regression-test`](../../.agents/skills/write-regression-test/SKILL.md) skill. Cover at least: gate-off no-op, cache-hit reuse, claim race (CAS returns `None`), persist `DONE`/`FAILED`, terminalization on every error code. Reset `STTService._instance = None` in fixtures (singleton).

---

## 3. Manual release gates (block ENABLING, not code completion)

These are manual/operational gates that must pass before STT is **enabled in production**. Per [parent §13.3](media-transcription-stt-v1.md) + [lib/stt spec §10(b)](lib-stt-v1.md), automated `lib/stt` + integration can be code-complete **and default-off** while these remain open — STT ships behind `[stt].enabled = false` + per-chat `TRANSCRIBE_MEDIA` (both off by default), so green code does not enable any billable behavior until an operator turns it on.

Carried forward (the two most actionable called out, then the rest):

- [ ] **gate-1 — live-wire `getRecognition` framing.** lib/stt §7.3 is **PROVISIONAL**. Actionable NOW via the aurumentation golden suite's recorded fixtures: inspect the real response framing in [`tests/lib/stt/golden/data/*.json`](../../tests/lib/stt/golden/data) vs `_resolveEnvelope` in [`lib/stt/providers/yandex_events.py`](../../lib/stt/providers/yandex_events.py), adjust if needed. **This is the single highest-risk known-unknown.**

- [ ] **gate-5 — RSS / decoded-memory budget.** Tied to the accepted decoded-memory gap (§4): `lib/stt` does NOT bound decoded PCM memory; the service bounds source bytes + the handler bounds duration BEFORE the provider decodes. Measure the real spike under those caps. **If gate-5 fails, revisit restoring a decoded-buffer cap INSIDE `lib/stt` (the one cap that can only live in the decode path).**

- [ ] **gate-2** — model confirmation (`general` vs `deferred-general` for this workload).
- [ ] **gate-3** — inline-limit semantics (confirm 60 MB inline vs base64 expansion; product stays at the conservative default regardless).
- [ ] **gate-4** — 10-min end-to-end latency. If p95 processing exceeds the existing media poll, reduce default duration or redesign originating-turn waiting — **never** attach an unbounded worker task.
- [ ] **gate-6** — graceful shutdown during a max-size decode; verify the deployment supervisor's external hard-kill grace policy for a simulated native hang.
- [ ] **gate-7** — `make ci` Alpine-wheel proof (pinned PyAV wheel works in the Alpine container).
- [ ] **gate-8** — PyAV encoder availability (`libopus` / `libmp3lame` present in the `av==18.0.0` wheel on every target platform). *(Already verified present.)*
- [ ] **gate-9** — quality-by-format (UNVERIFIED): one clip recognized pass-through (OGG_OPUS) and transcoded, compared. Proven win is size/traffic, not quality.

Plus SpeechKit auth smoke + end-to-end smoke — see parent §13.3 for the full operational list. No secrets, full audio, full transcripts, or authorization headers may be stored in smoke-test artifacts.

---

## 4. Open design notes / deferred nits

- **Prompt-injection mitigation placement** — the OPEN DESIGN above (handler wraps? shared prompt-builder helper? restore in the formatter?). Decision required this round; the thin formatter deliberately shed it (ADR-020 decision 7).

- **Accepted decoded-memory gap.** `lib/stt` does not bound decoded PCM; `STTService` bounds source bytes (`max-source-bytes`, post-download) and the handler bounds duration BEFORE calling `stt()`. Revisit (restore a decoded-buffer cap inside `lib/stt`'s decode path) **if gate-5 fails**. Documented in the `extractAudio` docstring + [`lib-stt-v1.md`](lib-stt-v1.md).

- **`**extraKwargs` config-typo-swallow in `YandexSpeechKitProvider.__init__`** ([`yandex_speechkit.py:162`](../../lib/stt/providers/yandex_speechkit.py)) — the constructor accepts arbitrary kwargs, so a misspelled `[stt]` key (e.g. `folde-id`) is silently swallowed instead of raising at startup. A deferred nit — could filter explicitly against the known key set, or drop `**extraKwargs` and let unexpected keys raise. Not blocking.

- **`transcribe-media` enum↔TOML-key invariant is intentionally NOT covered by a dedicated test (accepted trade-off).** The dedicated `TRANSCRIBE_MEDIA` unit tests (existence + enum↔TOML-key invariant) were deliberately deleted as low-value — the setting is exercised end-to-end by its `STTHandler` consumer (`chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()`), which surfaces any wiring drift at handler time. This is an accepted trade-off (no dedicated drift-guard test), not a gap to fill.

- **Uncommitted working tree.** Everything above (lib/stt simplified + STTService stateless + `TRANSCRIBE_MEDIA` 3-of-4 sites + aurumentation/doc work) is **uncommitted** on `add-audio-transcribation-v2`. Review/commit before or during the handler round so the handler round starts from a clean base.

- **§7.2 delete-ordering (load-bearing, do not "fix").** The provider runs its best-effort `DELETE` in `finally` (before parse) — an intentional refinement of "after fetch and parse". Documented in [lib/stt spec §7.2](lib-stt-v1.md) + a load-bearing code comment.

---

*Sibling plan docs (same directory): [parent plan](media-transcription-stt-v1.md), [lib/stt spec](lib-stt-v1.md).*
