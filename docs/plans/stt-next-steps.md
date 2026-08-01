# STT Feature — Next Steps

> **Status:** `lib/stt` implemented + simplified; **`STTService` IMPLEMENTED as a
> stateless service** (default-off, unwired — no handler yet). Remaining: handler
> (owns the full `media_attachments` row lifecycle) + chat setting + bounded
> platform download + prompt-injection mitigation + user-visible docs/CHANGELOG.
>
> Scope: this is a working roadmap for completing the Speech-to-Text feature.
> It tracks what is done, what is in flight, and what remains. Reference docs:
> the [parent plan](media-transcription-stt-v1.md) (product decisions D1–D8,
> integration §11/§12, manual release gates §13.3) and the [lib/stt spec](lib-stt-v1.md)
> (library contracts).

---

## 1. Current state

- `lib/stt/` is a provider-neutral Speech-to-Text library: **implemented, lint-clean,
  and test-green**, default-off everywhere. The transcript formatter moved out of
  `lib/stt` to a thin [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py)
  (`lib/stt/formatter.py` was deleted; the old header/escape/truncate/sentinel
  contracts were shed — see [`lib-stt-v1.md`](lib-stt-v1.md) §6).
- **`STTService` is IMPLEMENTED as a stateless service** (default-off, unwired —
  no handler yet) at `internal/services/stt/service.py` (singleton,
  `STTService.getInstance()`). It owns ONLY the provider lifecycle and a thin
  never-raise transcription entry, `async transcribeMedia(data: bytes, *, chatId) -> STTOutcome`.
  It is wired to `[stt]` config and `ProxyService.resolveProxy(...)`, but performs
  **NO DB I/O** — no row read/insert/cache/claim/persist/reclaim. No bot handler
  triggers it yet. See ADR-020 in [`architecture.md`](../llm/architecture.md) for
  the stateless-pipeline + dependency-firewall decision.
- Work lives on branch `add-audio-transcribation-v2`.
- The 2026-08-02 simplification reshaped both the library and the service:
  - Dropped `STTManager` — the configured provider is now held directly by
    `STTService`.
  - Removed caps from `extractAudio` — source-byte bounding is now the service's
    responsibility (post-download, on caller-supplied `bytes`); duration bounding
    is deferred to the handler round.
  - Made `AbstractSTTProvider.stt(data)` the **never-raise** entry point: it wraps
    extract + transcribe and converts any extraction exception into a
    `TranscriptionResult(ERROR, …)`.
  - **Stateless service:** the DB-backed 11-step pipeline (read/insert/cache/claim/
    persist/reclaim) was removed. `STTService.transcribeMedia` now takes raw
    `bytes` + a `chatId` keyword and returns an `STTOutcome`; the future handler
    owns the full `media_attachments` row lifecycle (read/cache-hit, claim/orphan-
    reclaim to `PENDING`, persist via the existing `setStatusVerified` CAS,
    terminalize). `STTMediaRequest` was REMOVED (dead).
  - **Thin formatter:** `lib/stt/formatter.py` deleted; reborn at
    `internal/services/stt/formatter.py`. Emits `[HH:MM:SS.mmm] text` lines only
    (no untrusted-data header, no XML escaping, no truncation, no
    `[No speech detected]` sentinel). `NO_SPEECH` → `DONE` with `description=""`.
    Prompt-injection mitigation (the dropped header) is now the handler's job —
    see §3.
  - **Unbounded admission:** `async with self._semaphore` with NO `asyncio.timeout`.
    The admission-timeout was removed; `ADMISSION_TIMEOUT` was renamed →
    `STT_DISABLED` (produced when `[stt].enabled = false`). The handler bounds the
    originating turn via its pipeline timeout.
  - **Provider-owned validation:** `STTService.initialize(configManager)` (no
    `database` arg) validates only the provider name; `YandexSpeechKitProvider.__init__`
    owns cred / `${...}`-placeholder / cap-positivity / cross-field validation.

## 2. lib/stt cleanup (DONE)

Post-simplification cleanup applied to `lib/stt/`:

- [x] `stt(data)` made never-raise (wraps `extractAudio`; extraction exceptions →
      `TranscriptionResult(ERROR)`).
- [x] Deleted dead cap-exception classes + the `AUDIO_TOO_LARGE` enum value
      (caps removed → never raised from `lib/stt`).
- [x] Rewrote stale docstrings (`extractAudio` no longer claims caps); fixed 4
      `STTManager` docstring references.
- [x] Added `toYandexSpeechKit()` test; aligned return type.
- [x] **Accepted trade-off (user decision):** `extractAudio` does **NOT** bound
      decoded PCM memory — a large/long source can decode to hundreds of MB. The
      owning layer MUST bound source bytes before calling `extractAudio`. (For the
      service that is `max-source-bytes`; duration bounding is the handler's job.)
      Documented in the `extractAudio` docstring.
- [x] `docs/plans/lib-stt-v1.md` updated to match the simplified shape (incl. §6
      formatter-moved-out note). NOTE: minor docstring drift in
      `lib/stt/__init__.py` is flagged for a separate tiny pass.

## 3. STTService integration

`STTService` is **IMPLEMENTED as a stateless service** (default-off). The
service-level pipeline is complete and test-green. Per [parent §11.3](media-transcription-stt-v1.md)
+ §11 config + §12 handler.

What remains for the feature to become user-visible is the **handler round**
(§3.3 / §3.4 / §3.5 below).

### 3.1 Service — `internal/services/stt/` — DONE

Stateless singleton `STTService` (`internal/services/stt/service.py`). It owns:

- [x] **`transcribeMedia(data, *, chatId) -> STTOutcome`** — the never-raise
      stateless entry. Pipeline: `STT_DISABLED` (when not enabled) →
      `SOURCE_TOO_LARGE` (when `len(data) > maxSourceBytes`) → per-chat/global
      rate limiters → `async with self._semaphore` (NO timeout) →
      `await provider.stt(data)` → `_mapOutcome` (FINAL/NO_SPEECH → `DONE` +
      `formatTranscript`; ERROR → `FAILED` + provider errorCode). Only
      `asyncio.CancelledError` propagates.
- [x] **Proxy resolution**: resolve the `stt` proxy via
      `ProxyService.resolveProxy(sttConfig, "stt")`; construct the
      `YandexSpeechKitProvider` with the resolved `ProxyConfig`. (Proxy is
      injected, never resolved inside `lib/stt` — see [lib/stt spec §1](lib-stt-v1.md).)
- [x] **Provider-owned validation**: the service validates ONLY the provider name
      via `STT_PROVIDERS_MAP`; `YandexSpeechKitProvider.__init__` owns
      cred/`${...}`/cap-positivity/cross-field validation (different providers
      have different params, so each validates its own).
- [x] **Lifecycle**: owns `provider.aclose()` on shutdown — best-effort, must not
      block shutdown.
- [x] **Config + skeleton + singleton + lifecycle + provider injection**: the
      `[stt]` TOML section, the `STTService` class, `getInstance()`, startup/
      shutdown hooks, and the `YandexSpeechKitProvider` injection are all in
      place (see [`docs/llm/configuration.md`](../llm/configuration.md) `[stt]`
      and [`docs/llm/services.md`](../llm/services.md) §7).
- [x] **No DB I/O**: the service does not touch `media_attachments`. The row
      lifecycle is the handler round's responsibility (§3.3).

### 3.2 Config — `[stt]` section — DONE

- [x] Wired the flat TOML config: `enabled`, `provider`, `api-key`, `folder-id`,
      `model`, `language`, `max-source-bytes` (default raised to 1 GiB),
      `max-concurrency`, the `*-seconds` timeout/poll keys, `max-result-bytes`,
      and the two rate-limiter queue names. DELETED: `max-duration-seconds`,
      `max-transcript-chars`, `admission-timeout`, and the old non-`-seconds`
      spellings (`request-timeout`, `operation-timeout`, `poll-initial-delay`,
      `poll-max-delay`).
- [x] TOML shape: parent §11.1 (`configs/00-defaults/stt.toml`).
- [x] Validation (parent §11.2): `enabled=false` ⇒ do not instantiate the
      provider / load PyAV / validate credentials; `enabled=true` ⇒ the service
      validates the provider name, the provider constructor validates its own
      params (creds/`${...}`/caps/cross-field), and `ProxyService.resolveProxy`
      may raise.

### 3.3 Handler — REMAINING (next round)

- [ ] Register a new `STTHandler` in `internal/bot/common/handlers/`, gated on
      `TRANSCRIBE_MEDIA` (friend tier) **and** `[stt].enabled`. Intercepts
      inbound voice/audio/video, **owns the full `media_attachments` row
      lifecycle** (read/cache-hit, claim/orphan-reclaim to `PENDING`, persist the
      `STTOutcome` via the existing `setStatusVerified` CAS, terminalize),
      renders the transcript into the multi-attachment TEXT content. (Parent §12.)
      **Must be registered before `LLMMessageHandler`** (the catch-all) — load
      the [`add-handler`](../../.agents/skills/add-handler/SKILL.md) skill when
      this lands.
- [ ] **Bounded `downloadAttachment(maxBytes=…)` platform extension** — the
      handler builds the raw `bytes` for `transcribeMedia`; promote the
      `max-source-bytes` bound into a `maxBytes=` arg on the platform download
      path so the limit is enforced at the socket, not after the full body is
      buffered. (Emits `SOURCE_SIZE_UNKNOWN` / `DOWNLOAD_ERROR` on failure —
      these codes are reserved on the enum for the handler.)
- [ ] **Prompt-injection mitigation** (accepted trade-off from the thin formatter
      — ADR-020 decision 7): the untrusted-data header that the old `lib/stt`
      formatter dropped is now the handler / prompt-construction layer's
      responsibility. Wire it when the handler ships (e.g. the untrusted-data
      label + never-system-role injection per parent §6.1/§12).
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
- **Enum disposition (8 members).** `STTErrorCode` ownership post-simplification:
  - **Service-produced** (produced ONLY by `STTService`): `STT_DISABLED`, `SOURCE_TOO_LARGE`.
    (`PROVIDER_ERROR` is also produced by the service as the catch-all fallback
    for unexpected exceptions — structured logs distinguish a service-caught
    fallback from a provider-returned `PROVIDER_ERROR`.)
  - **Provider-produced** (returned inside a `TranscriptionResult(ERROR, …)` from
    `provider.stt()`): `NO_AUDIO`, `PROVIDER_ERROR`, `PROTOCOL_ERROR`.
  - **Reserved for the future handler** (not currently produced): `SOURCE_SIZE_UNKNOWN`,
    `DOWNLOAD_ERROR`, `DURATION_EXCEEDED`. The handler round owns the bounded
    download (`SOURCE_SIZE_UNKNOWN` / `DOWNLOAD_ERROR`) and any duration gating
    (`DURATION_EXCEEDED`); until it lands these are vocabulary only.
  - `ADMISSION_TIMEOUT` was **renamed → `STT_DISABLED`** (the admission-timeout
    was removed; admission is unbounded). `AUDIO_TOO_LARGE` was **deleted** in
    the earlier lib/stt simplification.
- **§7.2 delete-ordering.** The provider runs its best-effort `DELETE` in
  `finally` (before parse) — an intentional refinement of "after fetch and
  parse". Documented in [lib/stt spec §7.2](lib-stt-v1.md) + a load-bearing code
  comment. Do not "fix" it to match a literal reading.
