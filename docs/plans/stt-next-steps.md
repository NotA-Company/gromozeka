# STT Feature — Next Steps

> **Status:** lib/stt implemented + simplified (unwired); integration pending.
>
> Scope: this is a working roadmap for completing the Speech-to-Text feature.
> It tracks what is done, what is in flight, and what remains. Reference docs:
> the [parent plan](media-transcription-stt-v1.md) (product decisions D1–D8,
> integration §11/§12, manual release gates §13.3) and the [lib/stt spec](lib-stt-v1.md)
> (library contracts, currently being rewritten to match the simplified shape).

---

## 1. Current state

- `lib/stt/` is a provider-neutral Speech-to-Text library: **implemented, lint-clean,
  and test-green** (~3,631 tests), but **not wired into any service/handler/config**.
  It is default-off everywhere.
- Work lives on branch `add-audio-transcribation-v2`.
- The user just **simplified** the library:
  - Dropped `STTManager` — the configured provider is now used directly by the
    (forthcoming) service.
  - Removed caps from `extractAudio` — caps are now the **service's** responsibility.
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

## 3. STTService integration (the next major phase)

This is where the feature becomes user-visible (behind the `TRANSCRIBE_MEDIA`
friend gate). Per [parent §11.3](media-transcription-stt-v1.md) + §11 config +
§12 handler.

### 3.1 Service — `internal/services/stt/`

Singleton `STTService`. It owns:

- [ ] **Admission** (parent §8.2): bounded concurrency + the source-byte/duration
      caps that `lib/stt` no longer enforces.
- [ ] **Media download** (parent §8.3): bounded platform download, producing the
      raw `bytes` for `extractAudio`.
- [ ] **Proxy resolution**: resolve the `stt` proxy via
      `ProxyService.resolveProxy(sttConfig, "stt")`; construct the
      `YandexSpeechKitProvider` with the resolved `ProxyConfig`. (Proxy is
      injected, never resolved inside `lib/stt` — see [lib/stt spec §1](lib-stt-v1.md).)
- [ ] **Transcription**: call `provider.stt(data)` (never-raise →
      `TranscriptionResult`).
- [ ] **Formatting** via `formatTranscript` — FINAL/NO_SPEECH only; ERROR →
      FAILED + null description.
- [ ] **Persistence**: write the transcript into `media_attachments.description`
      (existing column, **no migration** per D4/D5).
- [ ] **Lifecycle**: own `provider.aclose()` on shutdown — best-effort, must not
      block shutdown. (The deleted `STTManager`'s defensiveness moves here.)

### 3.2 Config — `[stt]` section

- [ ] Wire the TOML config: enabled flag, `api-key`, `folder-id`, `model`, and
      the source/duration/inline caps the service now owns.
- [ ] TOML shape: parent §11.1 (`configs/00-defaults/stt.toml`).
- [ ] Validation (parent §11.2): `enabled=false` ⇒ do not instantiate the
      provider / load PyAV / validate credentials; `enabled=true` ⇒ fail startup
      on missing creds, unresolved `${...}`, unknown provider, non-positive
      limits, missing PyAV, missing rate-limiter queue mappings.

### 3.3 Handler

- [ ] Register (or extend) a media handler gated on `TRANSCRIBE_MEDIA`
      (friend tier) **and** `[stt].enabled`. Intercepts inbound voice/audio/video,
      triggers the service, renders the transcript. (Parent §12.)
- [ ] **TEXT media rendering must reuse the already-computed multi-attachment
      content** (readiness correction #3) — do not recompute and lose Max
      per-item descriptions.

### 3.4 Friend gate

- [ ] `TRANSCRIBE_MEDIA` chat setting — `ChatSettingsPage.FRIEND`, default-off.
      Wire across all four sites (enum value, `_chatSettingsInfo`, default TOML,
      consumer). Use the `add-chat-setting` skill.

### 3.5 User-visible docs (entry belongs HERE, when the feature ships — NOT with lib/stt)

- [ ] `CHANGELOG.md` — one user-visible `Added` entry under `Unreleased`.
- [ ] `docs/llm/libraries.md` + `docs/llm/services.md` + `README.md` per
      parent §14 (load `update-project-docs` for the full pass).

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
  was **deleted**. Confirm the service uses these codes when integration lands.
- **§7.2 delete-ordering.** The provider runs its best-effort `DELETE` in
  `finally` (before parse) — an intentional refinement of "after fetch and
  parse". Documented in [lib/stt spec §7.2](lib-stt-v1.md) + a load-bearing code
  comment. Do not "fix" it to match a literal reading.
