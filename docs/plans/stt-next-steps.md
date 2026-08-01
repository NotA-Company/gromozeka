# STT Feature — Next Steps

> **Status:** `lib/stt` implemented + simplified; **`STTService` IMPLEMENTED**
> (default-off, unwired — no handler yet). Remaining: handler + chat setting +
> bounded platform download + user-visible docs/CHANGELOG.
>
> Scope: this is a working roadmap for completing the Speech-to-Text feature.
> It tracks what is done, what is in flight, and what remains. Reference docs:
> the [parent plan](media-transcription-stt-v1.md) (product decisions D1–D8,
> integration §11/§12, manual release gates §13.3) and the [lib/stt spec](lib-stt-v1.md)
> (library contracts, currently being rewritten to match the simplified shape).

---

## 1. Current state

- `lib/stt/` is a provider-neutral Speech-to-Text library: **implemented, lint-clean,
  and test-green**, default-off everywhere.
- **`STTService` is IMPLEMENTED** (default-off, unwired — no handler yet): the full
  `transcribeMedia` pipeline is in place at `internal/services/stt/service.py`
  (singleton, `STTService.getInstance()`), wired to `[stt]` config and
  `ProxyService.resolveProxy(...)`, but no bot handler triggers it yet. See ADR-020
  in [`architecture.md`](../llm/architecture.md) for the synchronous-pipeline +
  dependency-firewall decision.
- Work lives on branch `add-audio-transcribation-v2`.
- The library was **simplified** before the service landed:
  - Dropped `STTManager` — the configured provider is now held directly by
    `STTService`.
  - Removed caps from `extractAudio` — caps are now the **service's** responsibility
    (admission + bounded download).
  - Made `AbstractSTTProvider.stt(data)` the **never-raise** entry point: it wraps
    extract + transcribe and converts any extraction exception into a
    `TranscriptionResult(ERROR, …)`.

## 2. lib/stt cleanup (in progress / just-applied)

Post-simplification cleanup being applied to `lib/stt/`:

- [x] `stt(data)` made never-raise (wraps `extractAudio`; extraction exceptions →
      `TranscriptionResult(ERROR)`).
- [x] Deleted dead cap-exception classes + the `AUDIO_TOO_LARGE` enum value
      (caps removed → never raised from `lib/stt`).
- [x] Rewrote stale docstrings (`extractAudio` no longer claims caps); fixed 4
      `STTManager` docstring references.
- [x] Added `toYandexSpeechKit()` test; aligned return type.
- [x] **Accepted trade-off (user decision):** `extractAudio` does **NOT** bound
      decoded PCM memory — a large/long source can decode to hundreds of MB. The
      `STTService` MUST bound source bytes **and** duration BEFORE calling
      `extractAudio`. Documented in the `extractAudio` docstring.
- [ ] `docs/plans/lib-stt-v1.md` being rewritten to match the simplified shape
      (§1/§2/§3/§4/§5/§8/§8.1/§9 were stale — manager removed, caps moved out,
      `stt()` is the never-raise entry point).

## 3. STTService integration

`STTService` is **IMPLEMENTED** (default-off). The service-level pipeline is
complete and test-green (~55 service tests: `tests/services/stt/test_service_lifecycle.py`
(31) + `tests/services/stt/test_transcribe.py` (24); full suite ~3705 passed).
Per [parent §11.3](media-transcription-stt-v1.md) + §11 config + §12 handler.

What remains for the feature to become user-visible is the **handler round**
(§3.3 / §3.4 / §3.5 below).

### 3.1 Service — `internal/services/stt/` — DONE

Singleton `STTService` (`internal/services/stt/service.py`). It owns:

- [x] **Admission** (parent §8.2): bounded concurrency + the source-byte/duration
      caps that `lib/stt` no longer enforces. Emits `STTErrorCode.ADMISSION_TIMEOUT`
      / `SOURCE_TOO_LARGE` / `SOURCE_SIZE_UNKNOWN` as appropriate.
- [x] **Media download** (parent §8.3): bounded platform download (current upper
      bound enforced here), producing the raw `bytes` for `extractAudio`. Emits
      `STTErrorCode.DOWNLOAD_ERROR` on failure. *(A bounded
      `downloadAttachment(maxBytes=…)` platform extension is still a remaining
      item — see §3.3.)*
- [x] **Proxy resolution**: resolve the `stt` proxy via
      `ProxyService.resolveProxy(sttConfig, "stt")`; construct the
      `YandexSpeechKitProvider` with the resolved `ProxyConfig`. (Proxy is
      injected, never resolved inside `lib/stt` — see [lib/stt spec §1](lib-stt-v1.md).)
- [x] **Transcription**: call `provider.stt(data)` (never-raise →
      `TranscriptionResult`).
- [x] **Formatting** via `formatTranscript` — FINAL/NO_SPEECH only; ERROR →
      FAILED + null description.
- [x] **Persistence**: writes the transcript into `media_attachments.description`
      via the repo helper `setStatusVerified` (existing column, **no migration**
      per D4/D5). Verified terminal states persist via a compare-and-set so a
      gate-off / already-verified row returns `DONE` with `description=None`
      without clobbering a real transcript.
- [x] **Lifecycle**: owns `provider.aclose()` on shutdown — best-effort, must not
      block shutdown. (The deleted `STTManager`'s defensiveness moved here.)
- [x] **Config + skeleton + singleton + lifecycle + provider injection**: the
      `[stt]` TOML section, the `STTService` class, `getInstance()`, startup/
      shutdown hooks, and the `YandexSpeechKitProvider` injection are all in
      place (see [`docs/llm/configuration.md`](../llm/configuration.md) `[stt]`
      and [`docs/llm/services.md`](../llm/services.md) §7).

### 3.2 Config — `[stt]` section — DONE

- [x] Wired the TOML config: enabled flag, `api-key`, `folder-id`, `model`, and
      the source/duration/inline caps the service now owns.
- [x] TOML shape: parent §11.1 (`configs/00-defaults/stt.toml`).
- [x] Validation (parent §11.2): `enabled=false` ⇒ do not instantiate the
      provider / load PyAV / validate credentials; `enabled=true` ⇒ fail startup
      on missing creds, unresolved `${...}`, unknown provider, non-positive
      limits, missing PyAV, missing rate-limiter queue mappings.

### 3.3 Handler — REMAINING (next round)

- [ ] Register a new `STTHandler` in `internal/bot/common/handlers/`, gated on
      `TRANSCRIBE_MEDIA` (friend tier) **and** `[stt].enabled`. Intercepts
      inbound voice/audio/video, triggers the service, renders the transcript.
      (Parent §12.) **Must be registered before `LLMMessageHandler`** (the
      catch-all) — load the [`add-handler`](../../.agents/skills/add-handler/SKILL.md)
      skill when this lands.
- [ ] **Bounded `downloadAttachment(maxBytes=…)` platform extension** — the
      service currently bounds total downloaded bytes itself; promote the bound
      into a `maxBytes=` arg on the platform download path so the limit is
      enforced at the socket, not after the full body is buffered.
- [ ] **TEXT media rendering must reuse the already-computed multi-attachment
      content** (readiness correction #3) — do not recompute and lose Max
      per-item descriptions.

### 3.4 Friend gate — REMAINING (next round)

- [ ] `TRANSCRIBE_MEDIA` chat setting — `ChatSettingsPage.FRIEND`, default-off.
      Wire across all four sites (enum value, `_chatSettingsInfo`, default TOML,
      consumer). **Load the [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md)
      skill** when this lands — missing any of the four sites leaves the setting
      half-wired and non-functional.

### 3.5 User-visible docs (entry belongs HERE, when the handler ships — NOT with the service skeleton)

- [ ] `CHANGELOG.md` — one user-visible `Added` entry under `Unreleased`
      (STTService is default-off/unwired, so the entry is intentionally deferred
      to the handler round).
- [ ] `docs/llm/handlers.md` — add the `STTHandler` row when it lands.
- [ ] `README.md` per parent §14 (load `update-project-docs` for the full pass).

## 4. Manual release gates (block ENABLING, not code-completion)

These are manual/operational gates that must pass before STT is **enabled in
production**. Per parent §16/§13.3, automated `lib/stt` + integration can be
code-complete **and default-off** while these remain open — STT ships behind
`[stt].enabled = false` + per-chat `TRANSCRIBE_MEDIA` (both off by default), so
green code does not enable any billable behavior until an operator turns it on.

Gate numbering follows the [lib/stt spec §10(b)](lib-stt-v1.md) (which expands
parent §13.3's 7 gates to 9 by splitting out encoder availability and
quality-by-format):

- [ ] **gate-1 — live-wire `getRecognition` framing.** lib/stt §7.3 is
      **PROVISIONAL** — verify the transport framing/content-type against real
      Yandex responses and adjust `yandex_events.py` if needed. (This is the
      single highest-risk known-unknown.)
- [ ] **gate-2 — model confirmation.** `general` vs `deferred-general` for this
      workload.
- [ ] **gate-3 — inline-limit semantics.** Confirm 60 MB inline vs base64
      expansion; product stays at the conservative 40 MiB default regardless.
- [ ] **gate-4 — 10-min end-to-end latency.** If p95 processing exceeds the
      existing 300 s media poll, reduce default duration or redesign
      originating-turn waiting — **never** attach an unbounded worker task.
- [ ] **gate-5 — RSS/memory budget.** ⚠️ **Note:** decoded memory is now
      **UNBOUNDED** in `lib/stt` per the accepted gap in §2 — measure the real
      spike under the service's source/duration caps. Reduce
      source/duration/concurrency defaults if the deployment budget can't absorb
      it.
- [ ] **gate-6 — graceful shutdown.** Exercise shutdown during a max-size
      decode; verify the deployment supervisor's external hard-kill grace policy
      for a simulated native hang.
- [ ] **gate-7 — `make ci` Alpine-wheel proof.** Pinned PyAV wheel works in the
      Alpine container.
- [ ] **gate-8 — PyAV encoder availability.** `libopus` / `libmp3lame` present in
      the `av==18.0.0` wheel on every target platform. *(Already verified
      present.)*
- [ ] **gate-9 — quality-by-format (UNVERIFIED).** One clip recognized
      pass-through (OGG_OPUS) and transcoded, compared. Proven win is
      size/traffic, not quality — treat any difference as observation, not
      design assumption.

Plus SpeechKit auth smoke + end-to-end smoke — see parent §13.3 for the full
operational list. No secrets, full audio, full transcripts, or authorization
headers may be stored in smoke-test artifacts.

## 5. Open design notes / deferred decisions

- **Decoded-memory gap (accepted).** `lib/stt` does not bound decoded PCM; the
  service bounds source + duration instead. If RSS **gate-5** fails, revisit —
  i.e. restore a decoded-buffer cap inside `extractAudio`.
- **`maxInlineBytes` routing change.** Removing it changed pass-through-vs-
  transcode routing to container-only: large supported containers are now sent
  inline → more traffic / potential vendor 60 MB rejections. Monitor; restore
  inline-cap-driven routing if traffic/rejections become a problem.
- **Guarded import removed.** `import lib.stt` now hard-requires PyAV (`av` is
  always installed, so the breakage is latent). If a future module wants `lib/stt`
  types without PyAV, restore the `_PYAV_AVAILABLE` guard pattern.
- **Enum disposition.** `STTErrorCode` keeps service-layer codes
  (`ADMISSION_TIMEOUT` / `SOURCE_TOO_LARGE` / `SOURCE_SIZE_UNKNOWN` /
  `DOWNLOAD_ERROR` / `DURATION_EXCEEDED`) as shared vocabulary; `AUDIO_TOO_LARGE`
  was **deleted**. **Confirmed in `STTService`:** `ADMISSION_TIMEOUT`,
  `SOURCE_TOO_LARGE`, `SOURCE_SIZE_UNKNOWN`, and `DOWNLOAD_ERROR` are now
  produced by the service pipeline (admission + bounded download paths).
  `DURATION_EXCEEDED` is **reserved but not yet produced** — there is no
  upstream duration signal wired into the service, so duration gating remains
  deferred (open item: see §3.3 handler round / a future duration probe).
- **§7.2 delete-ordering.** The provider runs its best-effort `DELETE` in
  `finally` (before parse) — an intentional refinement of "after fetch and
  parse". Documented in [lib/stt spec §7.2](lib-stt-v1.md) + a load-bearing code
  comment. Do not "fix" it to match a literal reading.
