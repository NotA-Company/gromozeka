# Design: lib/stt v1 (first implementation step)

Status: **IMPLEMENTED (simplified shape) — lib/stt built; integration pending**  
Date: 2026-08-01  
Owner: TBD  
Companion docs: [`media-transcription-stt-v1.md`](./media-transcription-stt-v1.md) (parent), [`stt-next-steps.md`](./stt-next-steps.md) (integration roadmap + accepted gaps), [`architecture.md`](../llm/architecture.md), [`libraries.md`](../llm/libraries.md), [`configuration.md`](../llm/configuration.md), [`services.md`](../llm/services.md)

> Companion to and extracted from [`docs/design/media-transcription-stt-v1.md`](./media-transcription-stt-v1.md);
> ratifies its D1–D8. The `lib/stt` library described here is **implemented** (and has since been
> **simplified**: no `STTManager`, no caps inside `extractAudio`, a never-raise `stt(data)` entry). This
> document is the single source of truth for `lib/stt` internals; where it previously described the
> pre-simplification design it now matches the code. Integration status + open gaps live in
> [`stt-next-steps.md`](./stt-next-steps.md).

This document reorganizes the `lib/stt/`-relevant content of the reviewed parent plan into a
self-contained specification for the **first implementation step** (parent §13.1 steps 2 and 3).
`lib/stt/` is the one piece of the feature that is genuinely decoupled: parent §5.1 forbids it from
importing `internal.bot`, `internal.database`, or any singleton service, so it can be specified,
built, and unit-tested in isolation (mock transports, no DB, no bot event loop). Nothing here
re-litigates a ratified decision; it only makes the `lib/stt` contracts crisp and grounds them in
repo conventions. Where a consumer context is needed, a one-line cross-reference points back to the
parent (`consumed by STTService / handlers per parent §X`).

## 1. Purpose & dependency firewall

`lib/stt/` is the provider-neutral Speech-to-Text library: provider-neutral data models, a typed
exception taxonomy, PyAV-based audio extraction with **container-driven format negotiation** (probe →
pass-through / transcode, channel-preserving), transcript formatting, an abstract provider exposing a
never-raise `stt(data)` entry, and a single concrete provider (Yandex SpeechKit v3) which the
integration layer holds directly. It owns no DB rows, no bot state, no admission/concurrency policy,
no caps, and no config reading.

**In / out boundary.**

- **In scope for `lib/stt`:** models (incl. format descriptors), exceptions, audio extraction with
  format negotiation, transcript formatting, the Yandex wire protocol, event parsing, and the abstract
  + concrete provider surface. Caps (source bytes, duration, inline payload) are **out of scope** — see
  §5 ("accepted decoded-memory gap") and §8.1.
- **Out of scope (owned by `STTService` / handlers, per parent §5.1, §6, §8.2, §8.3, §11, §12):** the
  keyed in-flight task registry, DB status transitions, admission/rate-limit/semaphore policy, the
  bounded platform media download (parent §8.3), attachment storage, config parsing, all caps
  (source-byte / duration / inline-payload), and `STTMediaRequest` (parent §7 — service-side, carries
  media/chat IDs, optional platform `declaredSize`). These are referenced here only as "consumed by
  STTService per parent §X"; integration status lives in [`stt-next-steps.md`](./stt-next-steps.md).

**Dependency firewall — two seams (load-bearing contract #1).**

1. **Proxy is injected, never resolved inside `lib/stt`.** `YandexSpeechKitProvider.__init__` accepts
   an already-resolved `ProxyConfig` and spreads `proxyConfig.toKwargs()` into its `httpx.AsyncClient`
   — exactly the pattern in [`lib/yandex_search/client.py`](../../lib/yandex_search/client.py) and
   [`lib/openweathermap/client.py`](../../lib/openweathermap/client.py) (constructor stores
   `self._proxyConfig`, call site spreads `toKwargs()`). `lib/stt` must **not** call
   `ProxyConfig.fromServiceConfig()` itself: per parent §9 that bypasses per-service proxy lifecycle
   registration. Resolution happens in the main/service layer via
   `ProxyService.resolveProxy(sttConfig, "stt")`
   ([`internal/services/proxy/service.py:141`](../../internal/services/proxy/service.py)), which both
   resolves the config **and** registers the lifecycle.
2. **`extractAudio` takes raw `bytes`; the service provides those bytes from its bounded download.**
   `lib/stt` never imports bot download code. `extractAudio(data: bytes, supportedInputFormats)` (§5)
   receives the already-downloaded source bytes and the provider's ordered accepted containers — and
   nothing else. The service is responsible for bounding the download (source bytes + duration)
   *before* calling `extractAudio` (or the never-raise `stt(data)` entry); `lib/stt` does not re-check
   those bounds (see the "accepted decoded-memory gap" in §5). The old "typed async loader callable /
   `STTLoaderResult`" seam is **gone** — the boundary is now a plain `bytes` argument.

**Precedent.** `lib/stt/` sits alongside other bot-free libraries — [`lib/ai/`](../../lib/ai/manager.py),
[`lib/rate_limiter/`](../../lib/rate_limiter/), [`lib/markdown/`](../../lib/markdown/),
[`lib/yandex_search/`](../../lib/yandex_search/) — which all follow the same "no `internal.bot` /
`internal.database` / singleton-service imports" rule. The post-simplification shape dropped the
`STTManager` indirection: there is no manager analogous to
[`LLMManager`](../../lib/ai/manager.py); the integration layer holds the single configured provider
directly (§8).

## 2. Prerequisites

**PyAV dependency.** Pin `av==18.0.0` (parent §8.4, step 1). Add it under the `# Runtime` section of
[`requirements.direct.txt`](../../requirements.direct.txt); regenerate the frozen
[`requirements.txt`](../../requirements.txt) via the repo's freeze workflow. **Never edit
`requirements.txt` by hand** (AGENTS.md "Hard rules"). This doc only records the requirement — it does
not perform it.

Supported wheels bundle FFmpeg libraries on published platforms (current macOS, manylinux, and
musllinux artifacts). Source builds still require FFmpeg development libraries; do not claim that
system FFmpeg is never needed on unsupported platforms (parent §8.4).

**Encoder availability prerequisite (multi-format).** The transcode path encodes to OGG_OPUS (libopus)
and may encode to MP3 (libmp3lame). Verify these encoders are present in the pinned `av==18.0.0`
wheel on every target platform (almost certainly yes for the published manylinux/musllinux/macOS
artifacts, but confirm before release — see §10(b)). Missing encoders downgrade the transcode target
rather than silently corrupting output: the negotiation raises `EncoderError` on an unsupported encode
instead of emitting a malformed container.

**PyAV import is unconditional (no guarded import — simplification trade-off).** The pre-simplification
design used a module-level guarded `try/except ImportError` with a private `_PYAV_AVAILABLE` flag so the
`lib/stt` package imported cleanly without PyAV when STT was disabled. **That guard is gone.** The
simplification removed it: [`lib/stt/audio.py`](../../lib/stt/audio.py) does `import av` unconditionally,
and [`lib/stt/abstract.py`](../../lib/stt/abstract.py) does `from . import audio`, so **any** `import
lib.stt.*` now hard-requires PyAV at import time. This is an accepted trade-off for simplicity
(documented in [`stt-next-steps.md`](./stt-next-steps.md) §5 "open design notes"): PyAV (`av==18.0.0`)
is always present in the frozen environment, so the breakage is latent — but the old "lib/stt imports
cleanly without PyAV" claim no longer holds. If a future module wants `lib/stt` types without PyAV,
restore the `_PYAV_AVAILABLE` guard pattern (AGENTS.md "Hard rules" specifies the exact
`try/except ImportError` shape, the no-PEP-695-`type`-alias caveat, and the empty-`except`-branch
rule).

**Startup semantics.** When STT is disabled (`[stt].enabled = false`), the provider is never
constructed (the integration layer gates construction on the enabled flag), but the `lib.stt` package
still imports PyAV at import time (see above). When STT is **enabled**, a missing/unusable PyAV install
surfaces as a startup error at first use (parent §8.4, §11.2). There is no `_AVAILABLE` flag anymore;
it is not part of any public type.

## 3. Module layout

Eight files (parent §5.1's eight, plus `providers/yandex_events.py` isolated per
readiness correction #2, **minus the deleted `manager.py` and the deleted `formatter.py`**):

```text
lib/stt/
  __init__.py                      # public re-exports (models, abstract, exceptions, extractAudio, YandexSpeechKitProvider) — NO manager, NO formatter
  abstract.py                      # AbstractSTTProvider: supportedInputFormats() METHOD, async transcribe(), async stt(data) never-raise entry, async aclose()
  audio.py                         # extractAudio(data, supportedInputFormats) — PyAV probe + container-only format negotiation (pass-through/transcode); channel-preserving; unconditional `import av`; NO caps
  exceptions.py                    # typed extraction exceptions (3 subclasses), each mapping 1:1 to an STTErrorCode
  models.py                        # provider-neutral models, enums (incl. STTAudioContainerType + toYandexSpeechKit()), format descriptors (AudioFormatSpec)
  providers/
    __init__.py
    yandex_speechkit.py            # Yandex v3 wire protocol: submit/poll/get/delete + retry; supportedInputFormats() METHOD; held directly by the service
    yandex_events.py               # getRecognition streaming-JSON event parser (correction #2)
```

Correction #2 made the Yandex event parser an **isolated module** rather than inlined into the
provider, so it is independently unit-testable and the provider class stays focused on the wire
lifecycle. The simplification deleted `manager.py`: there is no `STTManager`, and the concrete
provider (`YandexSpeechKitProvider`) is the direct entry point held by the integration layer (§8).
The 2026-08-02 simplification also **deleted `formatter.py`**: the transcript formatter moved to
[`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py) and is now thin (§6).
Two things to notice in the public surface: `supportedInputFormats` is a **method**, not a
property (the abstract declares `def supportedInputFormats(self) -> Sequence[AudioFormatSpec]`);
and `AbstractSTTProvider.stt(data: bytes)` is a concrete (non-abstract) never-raise entry defined
on the base itself.

## 4. Provider-neutral models & exceptions

Use project naming and typing rules throughout (AGENTS.md "Hard rules"): `camelCase` for
members/functions/fields, `PascalCase` for classes, `UPPER_CASE` for constants, `StrEnum` (not
`Literal`) for string enums, dataclasses/`TypedDict` for records, full type hints, **no `Any`**, and
docstrings (`Args:`/`Returns:`) on every module/class/method/function/field.

All types below live in `models.py` unless noted.

**Enums.**

```python
from enum import StrEnum

class STTResultStatus(StrEnum):
    """Outcome category of a transcription attempt."""

    FINAL = "final"
    """One or more non-empty final segments were recognized."""

    NO_SPEECH = "no-speech"
    """Valid recognition completed with no non-empty final segments."""

    ERROR = "error"
    """An expected failure occurred; see the accompanying STTErrorCode."""


class STTErrorCode(StrEnum):
    """Stable, provider-neutral failure categories.

    Eight members, in three ownership groups (matches lib/stt/models.py):

      - Provider (surfaced by lib/stt via stt() and the Yandex provider):
        NO_AUDIO, PROVIDER_ERROR, PROTOCOL_ERROR.
      - STTService (the service is stateless — produces only these two):
        STT_DISABLED, SOURCE_TOO_LARGE.
      - Handler round (reserved; the handler owns media download, duration
        bounding, and the DB row lifecycle): SOURCE_SIZE_UNKNOWN,
        DOWNLOAD_ERROR, DURATION_EXCEEDED.

    The service/handler codes are NEVER produced inside lib/stt; they exist on
    the shared enum so their owners can surface them on a
    TranscriptionResult(ERROR, ...). See the raise/return contract below.
    """

    STT_DISABLED = "stt-disabled"
    """STTService vocabulary; never produced inside lib/stt."""

    SOURCE_TOO_LARGE = "source-too-large"
    """STTService vocabulary; never produced inside lib/stt."""

    SOURCE_SIZE_UNKNOWN = "source-size-unknown"
    """Reserved for the handler round; never produced inside lib/stt."""

    NO_AUDIO = "no-audio"
    """Surfaced by stt() from a NoAudioTrackError extraction failure."""

    DURATION_EXCEEDED = "duration-exceeded"
    """Reserved for the handler round; never produced inside lib/stt."""

    DOWNLOAD_ERROR = "download-error"
    """Reserved for the handler round; never produced inside lib/stt."""

    PROVIDER_ERROR = "provider-error"
    """Returned by the Yandex provider; also surfaced by stt() from an
    AudioDecodeError/EncoderError extraction failure or an unexpected exception."""

    PROTOCOL_ERROR = "protocol-error"
    """Returned by the Yandex provider (malformed response, trailing garbage,
    result body over the result-byte cap)."""
```

(The member names are the contract. The pre-simplification design had a ninth member,
`AUDIO_TOO_LARGE`; it is **deleted** — caps moved to the service, so nothing in `lib/stt` raises it
anymore. The shared-enum vocabulary codes above are retained so the service can surface them on
`TranscriptionResult(ERROR, ...)` without `lib/stt` ever producing them.)

```python
class STTAudioContainerType(StrEnum):
    """Audio containers a provider accepts inline.

    The string values are LOWERCASE internal labels, NOT the protobuf-JSON wire
    labels. The Yandex wire label is produced by `toYandexSpeechKit()`, which
    maps `wav` -> `WAV`, `ogg-opus` -> `OGG_OPUS`, `mp3` -> `MP3` — the three
    members of the Yandex SpeechKit v3 `ContainerAudio.ContainerAudioType` proto
    enum (there is no AIFF/AC3/FLAC in the enum). `RawAudio` / `LINEAR16_PCM` is
    intentionally not modelled here: v1 always submits a container, not
    headerless raw PCM.

    The lowercase internal values are freely chosen by the implementer (they are
    never written to the wire); `toYandexSpeechKit()` is what fixes the on-wire
    label. The Yandex provider's submit body always calls
    `audio.container.toYandexSpeechKit()` to set `container_audio.container_audio_type`.
    """

    WAV = "wav"
    OGG_OPUS = "ogg-opus"
    MP3 = "mp3"

    def toYandexSpeechKit(self) -> str:
        """Return the protobuf-JSON wire label for this container (§7.1)."""
        # match self: WAV -> "WAV", OGG_OPUS -> "OGG_OPUS", MP3 -> "MP3"; else ValueError.
```

**Records (frozen dataclasses, immutable tuples).**

```python
from dataclasses import dataclass
from typing import Optional, Tuple

@dataclass(frozen=True, slots=True)
class TranscriptionWord:
    """A single recognized word with its millisecond time range.

    Attributes:
        text: The recognized word text.
        startMs: Word start time in milliseconds.
        endMs: Word end time in milliseconds.
    """

    text: str
    startMs: int
    endMs: int


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    """A final recognized utterance.

    Attributes:
        text: The (normalized) segment text.
        startMs: Segment start time in milliseconds.
        endMs: Segment end time in milliseconds.
        words: Immutable tuple of TranscriptionWord, preserved in memory for
            future use even though only formatted text is persisted.
    """

    text: str
    startMs: int
    endMs: int
    words: Tuple[TranscriptionWord, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Provider-neutral result of one transcription attempt.

    Attributes:
        status: The outcome category.
        segments: Immutable tuple of TranscriptionSegment; empty unless FINAL.
        errorCode: Present iff status == ERROR; identifies the failure category.
    """

    status: STTResultStatus
    segments: Tuple[TranscriptionSegment, ...]
    errorCode: Optional[STTErrorCode] = None


@dataclass(frozen=True, slots=True)
class AudioFormatSpec:
    """One container format a provider accepts inline.

    Describes the negotiation surface used by `audio.py` to decide pass-through
    vs. transcode. Does NOT describe recognition quality — quality-by-format is
    UNVERIFIED (see §10(b)); the proven win is payload size/traffic.

    Attributes:
        container: The accepted container.
        minChannels: Minimum accepted channel count (inclusive).
        maxChannels: Maximum accepted channel count (inclusive). SpeechKit
            accepts multi-channel async audio, but the exact ceiling is
            unpublished; set a generous value here. Note: a `>2`-channel source
            routes to transcode only if unsupported, where the transcode path
            rejects it (`EncoderError` — opus/mp3 support at most 2 channels and
            the never-downmix hard rule makes >2-channel unrecoverable, §5); a
            >2-channel source in a supported container passes through unchanged.
        minSampleRate: Minimum accepted sample rate in Hz (inclusive).
        maxSampleRate: Maximum accepted sample rate in Hz (inclusive).
    """

    container: STTAudioContainerType
    minChannels: int
    maxChannels: int
    minSampleRate: int
    maxSampleRate: int


@dataclass(frozen=True, slots=True)
class ExtractedAudio:
    """Format-aware audio handed to a provider after negotiation.

    The container is whatever the negotiation decided — the source container on
    a pass-through path, or the transcode target (OGG_OPUS for Yandex) on a
    transcode path. `channels` is ALWAYS the source channel count; it is never
    downmixed (hard rule, §5).

    Attributes:
        container: The container of `data` (WAV / OGG_OPUS / MP3).
        channels: Channel count preserved from the source (no downmix).
        sampleRate: Sample rate of `data` in Hz.
        data: The audio bytes the provider receives (source bytes on
            pass-through, PyAV-re-encoded bytes on transcode). Base64 encoding
            happens at the provider, not here.
        durationMs: Measured duration in milliseconds, derived from the actual
            sample count (pass-through probe / transcode encode), not container
            metadata alone.
    """

    container: STTAudioContainerType
    channels: int
    sampleRate: int
    data: bytes
    durationMs: int
```

**Channel preservation (hard rule, user decision).** `ExtractedAudio.channels` always equals the
source channel count. The negotiation never downmixes — not on the pass-through path, not on the
transcode path. The multi-channel cost is no longer bounded inside `lib/stt` (caps moved out — §5);
the service's source+duration caps bound it indirectly. The transcode path rejects a `>2`-channel
source with `EncoderError` (opus/mp3 ceiling + never-downmix), but that is a codec-capability reject,
not a cap reject. See §5 for the decision flow.

**Loader boundary (gone — simplified to a `bytes` argument).** The pre-simplification design passed a
typed async loader callable into `lib/stt` (an `STTMediaLoader` returning an `STTLoaderResult` with
`data` / `fileSize` / `mimeType`). That seam is **deleted**. The boundary is now a plain `bytes`
argument to `extractAudio` (and to `stt(data)`) — the service supplies already-downloaded, already-bounded
bytes (§1 seam #2). There is no `STTLoaderResult` and no `STTMediaLoader` type in `models.py`.

The service-owned **immutable row-seed fields** (`fileId`, media type, metadata/prompt) that readiness
correction #1 calls out are `STTService`-side, **not** `lib/stt` — they are handled in the integration
doc ([`stt-next-steps.md`](./stt-next-steps.md) §3), not here. Correction #3 (TEXT media rendering must
reuse the already-computed multi-attachment content so Max per-item descriptions are not lost) is
handler/rendering-side and likewise out of scope here.

**Raise / return contract (load-bearing contract #2 — clarification made explicit).**

This is the uniform rule for failure handling across `lib/stt`:

1. **`stt(data)` and `transcribe()` never raise (the entire provider surface is never-raise).**
   `AbstractSTTProvider.stt(data: bytes)` (a concrete method on the base) wraps
   `extractAudio` + `transcribe`: it catches any `STTExtractionError` from extraction and maps it to
   `TranscriptionResult(status=ERROR, errorCode=exc.errorCode)`, catches any **other** exception and
   maps it to `TranscriptionResult(status=ERROR, errorCode=PROVIDER_ERROR)` (logged), and otherwise
   delegates to `transcribe()` — which is itself never-raise. So **calling `stt(data)` can never raise
   for any expected or unexpected failure** (extraction or transcription). This is the integration
   layer's convenience entry point. `STTService` (downstream) is the final never-raise boundary and
   maps an ERROR result to a terminal `FAILED` row (parent §6.2).
2. **The only runtime raise-point inside `lib/stt` is `audio.extractAudio()` when called DIRECTLY.**
   `extractAudio` raises the typed exceptions from `exceptions.py`. Each typed exception maps **1:1**
   to an `STTErrorCode` (see §5) and carries that code as a class attribute (`exc.errorCode`), so a
   direct caller can map the failure category without re-mapping. When called **via `stt(data)`**,
   nothing raises — extraction exceptions become ERROR results (point 1). Parent §6.2's outcome table is
   the authoritative mapping from failure category → `FAILED`.
3. **Constructors may raise on startup config validation when STT is enabled** (parent §11.2): missing
   credentials, unresolved `${...}` placeholders, non-positive limits. These are startup failures, not
   runtime `transcribe()` failures.

**Which `STTErrorCode` values are produced where:**

- Surfaced by `stt()` from extraction exceptions (raised by `audio.extractAudio()` only): `NO_AUDIO`
  (via `NoAudioTrackError`) and `PROVIDER_ERROR` (via `AudioDecodeError` / `EncoderError` for corrupt,
  truncated, decoder, muxer, or no-transcode-target failures, and via the unexpected-exception branch).
  See §5.
- Returned by the Yandex provider as `TranscriptionResult(ERROR, ...)`: `PROVIDER_ERROR` (operation
  error, exhausted auth/429/5xx/timeout) and `PROTOCOL_ERROR` (malformed JSON, trailing garbage, or
  streamed result body exceeding the result-byte cap) — see §7, §9.
- Produced by the **handler round** (never inside `lib/stt`, never by the stateless `STTService`):
  `SOURCE_SIZE_UNKNOWN`, `DOWNLOAD_ERROR`, `DURATION_EXCEEDED` — the handler owns media download,
  duration bounding, and the DB row lifecycle. Produced by **STTService** (the only two it emits):
  `STT_DISABLED`, `SOURCE_TOO_LARGE`. (parent §6.2, §8.2.) These never cross the `lib/stt` boundary;
  they exist on the shared enum so their owners can surface them.

## 5. Audio extraction contract

`lib/stt/audio.py` implements `extractAudio(data: bytes, supportedInputFormats: Sequence[AudioFormatSpec])`.
When called **directly**, it is the only runtime raise-point in `lib/stt` (load-bearing contract #2);
when called **via the provider `stt(data)` entry** (§4), nothing raises — extraction exceptions are
caught and surfaced as ERROR results. This section is the authoritative PyAV contract; the parent §8.4
summarizes and references it (nothing here is reproduced from the parent).

**Typed exceptions (`exceptions.py`), each mapping 1:1 to an `STTErrorCode`.** All subclass a common
`STTExtractionError` base and expose `errorCode: STTErrorCode`:

```text
STTExtractionError (base)
  NoAudioTrackError     -> STTErrorCode.NO_AUDIO        # no decodable audio stream
  AudioDecodeError      -> STTErrorCode.PROVIDER_ERROR  # corrupt / truncated source, decoder failure
  EncoderError          -> STTErrorCode.PROVIDER_ERROR  # encoder/muxer failure (libopus / libmp3lame), no transcode target, >2-channel source
```

(Each typed exception → exactly one code; multiple exception types may share a code. The exception
taxonomy is a clarification this doc pins — §4 fixes the exception→code mapping; the parent §7
summarizes the codes as "stable categories" and references §4. The pre-simplification design also had
`SourceTooLargeError` / `DurationExceededError` / `AudioTooLargeError` (the three cap exceptions); they
are **deleted** — caps moved out of `lib/stt`, so nothing raises them anymore.)

**`extractAudio()` negotiation contract (this section is authoritative; parent §8.4 summarizes it).**
Signature: `extractAudio(data, supportedInputFormats) -> ExtractedAudio`. **No caps** — the function
receives only the source bytes and the provider's ordered accepted containers; it does **NOT** bound
source byte length, decoded PCM memory, duration, or inline payload size. The caller (the future
`STTService`) is responsible for bounding source bytes AND duration BEFORE calling `extractAudio` (or
`stt(data)`) — see "Accepted decoded-memory gap" below. Runs via `asyncio.to_thread()`. This replaces
the prior "always normalize to mono s16/16 kHz WAV" contract with container-driven format negotiation;
it is a refinement within D3 (PyAV) and D8 (inline only), not a contradiction of either.

**Hard rule — always preserve source channels; never downmix (user decision).** Both the pass-through
and transcode paths carry the source channel count unchanged. The negotiation never downmixes.

**Decision flow.** `audio.py` receives the provider's ordered `supportedInputFormats` and produces an
`ExtractedAudio` via exactly one of two paths:

1. **Probe** the source with PyAV (header-level, no full decode yet): open the container from `BytesIO`,
   select the first decodable audio stream, and read container type, channel count, and sample rate
   (`_ProbeInfo`). Raise `NoAudioTrackError` if no decodable audio stream exists; raise `AudioDecodeError`
   on a corrupt/truncated probe (or a stream reporting non-positive channels/rate). Duration is **not**
   measured here — each path measures it from the actual sample count during its own decode.
2. **Choose the path** against the provider's `supportedInputFormats` (container-only — there is no
   payload/size routing anymore):
   - **Pass-through** when the source container matches one of the provider's `supportedInputFormats`
     (container match, with channel count and sample rate inside the matched `AudioFormatSpec`'s
     accepted ranges). Return the source bytes verbatim (preserve original channels and sample rate).
     This is the common case for Telegram `VOICE` (OGG_OPUS) and `AUDIO` (often MP3): no transcode.
   - **Transcode** when the source container is **not** in `supportedInputFormats`, **or** is supported
     but its channels/sample rate fall outside the matched `AudioFormatSpec`'s ranges. Encode to the
     provider's first supported compressed format (OGG_OPUS for Yandex — the first `supportedInputFormats`
     entry whose container is compressed). Preserve source channels (no downmix). If no compressed
     transcode target is available, raise `EncoderError`.
3. **Measure duration from the actual sample count**, not container metadata alone, on every path. The
   pass-through path decodes-and-discards frames purely to count samples (`_measureDuration`, no large
   PCM buffer accumulates); the transcode path counts the source-rate samples it feeds to the encoder.
4. **Finalize/close** the output container before reading bytes, and close both input and output PyAV
   containers in `finally` on **every** path (pass-through probe/measure and transcode encode alike) —
   success, exception, and cancellation.
5. **Return** `ExtractedAudio(container, channels, sampleRate, data, durationMs)` where `container` is
   the negotiated container (the source container on pass-through, the transcode target otherwise),
   `channels` is ALWAYS the source channel count, and `sampleRate` is the source rate on pass-through
   (or the Opus-native 48 kHz for an OGG_OPUS transcode target — Opus always produces a 48 kHz stream).

**Container mapping detail (`_mapContainerType`).** Maps the PyAV demuxer name + codec to one of the
three inline containers. The OGG mapping additionally requires `codecName == "opus"`: a Vorbis-in-OGG
source must NOT be mislabelled OGG_OPUS (it would pass through and fail provider-side decode) — a
non-opus OGG stream maps to `None` and routes to the transcode path. WAV and MP3 map on the format name
alone. Comma-separated demuxer aliases (e.g. the `mov,mp4,m4a,3gp,3g2,mj2` list for an MP4 container)
never alias one of the three inline containers and route to the transcode path.

**Channel ceiling on the transcode path.** Both transcode targets (libopus / libmp3lame) support at
most 2 channels, and the never-downmix hard rule makes a >2-channel source unrecoverable. A >2-channel
source routed to transcode is rejected up front with a clean `EncoderError` (in `_layoutForChannels`)
rather than emitting an invalid positional layout string (FFmpeg does not recognise names like `"3c"`).
The pass-through path carries the source channel count unchanged regardless — a multi-channel source in
a supported container (e.g. up to OGG_OPUS's 8-channel spec) passes through.

**Accepted decoded-memory gap (load-bearing contract #3, modified — user decision).** `extractAudio`
does **NOT** bound decoded PCM memory. A large/long source can decode to hundreds of MB of PCM during
probing/measurement/transcoding (e.g. ~100+ MB for long stereo audio). This is an **accepted trade-off
for simplicity**: the service bounds source bytes AND duration BEFORE calling `extractAudio`, which in
practice bounds the decoded-memory spike; `lib/stt` does not double-check those bounds and applies no
decoded-buffer cap. If parent §13.3 gate-5 (peak RSS) fails at integration, revisit — i.e. restore a
decoded-buffer cap inside `extractAudio` (see [`stt-next-steps.md`](./stt-next-steps.md) §5). This is
documented in the `extractAudio` docstring and the module docstring of [`audio.py`](../../lib/stt/audio.py).

**Cancellation & resource notes (part of the §5 contract; parent §8.4 summarizes it).** `asyncio.to_thread()`
cancellation does **not** stop native decoding. Do not use a coroutine timeout as the primary CPU/memory
control or assume cancellation killed the worker. The service's source + duration caps are the resource
controls (there are none inside `lib/stt` anymore); graceful-drain ordering protects dependencies while
work remains. Release the source buffer before base64/request construction so source, audio container,
base64, and serialized JSON do not all remain live at once.

**Shutdown limitation (part of the §5 contract; parent §8.4 summarizes it).** v1 deliberately drains tracked STT workers **without an
in-process hard shutdown deadline**; closing HTTP/DB dependencies underneath a live decoder would be
less safe. A pathological native-code hang can therefore delay graceful shutdown indefinitely.
Deployment supervision may impose an external hard-kill grace period. A hard application-level shutdown
SLA requires moving extraction to a killable subprocess and is a documented follow-up, not something
`asyncio` cancellation can provide.

**Caps ownership (load-bearing contract #3 — modified).** `audio.py` receives **no** caps. The
source-byte cap, the duration cap, and the inline-payload cap are all **STTService-owned**: the service
bounds the download + admission BEFORE calling `extractAudio`, and the (former) decoded-buffer cap is
intentionally absent (see "Accepted decoded-memory gap" above). The one thing `audio.py` still decides
is the pass-through-vs-transcode choice, and that decision is **container/range-only** — there is no
cap-driven routing. See §8.1 for the full cap-ownership table.

## 6. Transcript formatter — MOVED OUT of `lib/stt`

> **2026-08-02 simplification:** `lib/stt/formatter.py` was **DELETED**. The
> formatter now lives at [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py)
> and is **thin**. The `lib/stt` formatter contracts documented in earlier
> revisions of this section (the `UNTRUSTED_TRANSCRIPT_HEADER` constant, XML
> escaping of `&`/`<`/`>`, deterministic head/tail truncation to `maxTranscriptChars`
> around a single marker, and the `[No speech detected]` sentinel) are
> **obsolete** — they were intentionally shed. Load-bearing contract #5 about
> the header/truncation is **no longer a `lib/stt` contract**.

**New (thin) formatter shape** — see [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py):

- Pure function `formatTranscript(result: TranscriptionResult) -> str`. Consumes
  only `result.segments`; ignores `result.status`/`errorCode`.
- One line per non-empty segment: `[HH:MM:SS.mmm] text` with millisecond precision
  (the `.mmm` suffix is omitted when `milliseconds == 0`, yielding `[HH:MM:SS]`).
  Hours are zero-padded to a minimum width of 2.
- Empty segments (after stripping) are skipped; a result with all empty segments
  yields `""` (the `[No speech detected]` sentinel is gone).
- No untrusted-data header, no XML escaping, no truncation, no `maxTranscriptChars`
  parameter.
- The service maps `NO_SPEECH` → `DONE` with `description=""` (empty string).

**Accepted trade-off (prompt-injection mitigation deferred):** the old
`UNTRUSTED_TRANSCRIPT_HEADER` was a prompt-injection defense. Shedding it is an
accepted trade-off of the simplification — prompt-injection mitigation (the
untrusted-data label, XML escaping, never-system-role injection) becomes the
**handler / prompt-construction layer's responsibility** when the handler round
ships. See ADR-020 decision 7 in [`docs/llm/architecture.md`](../llm/architecture.md)
and [`docs/design/stt-next-steps.md`](stt-next-steps.md) §3.3. This is a tracked
handler-round TODO, not an accident.

## 7. Yandex SpeechKit v3 provider

`lib/stt/providers/yandex_speechkit.py` implements the wire protocol; this section is the authoritative
spec (parent §9 summarizes and references it). Authoritative
references: [async v3 guide](https://aistudio.yandex.ru/docs/en/speechkit/stt/api/transcribation-api-v3.html),
[v3 service proto](https://github.com/yandex-cloud/cloudapi/blob/master/yandex/cloud/ai/stt/v3/stt_service.proto),
[v3 message proto](https://github.com/yandex-cloud/cloudapi/blob/master/yandex/cloud/ai/stt/v3/stt.proto),
[SpeechKit limits](https://aistudio.yandex.ru/docs/en/speechkit/concepts/limits).

**Provider format surface.** `AbstractSTTProvider` exposes an ordered
`supportedInputFormats() -> Sequence[AudioFormatSpec]` — a **method** (not a property), the negotiation
input consumed by `audio.py` (§5). `YandexSpeechKitProvider.supportedInputFormats()` returns
`(OGG_OPUS, MP3, WAV)` — OGG_OPUS first because it is the preferred transcode target for speech
efficiency. The provider sets `container_audio.container_audio_type` dynamically from
`audio.container.toYandexSpeechKit()` (§7.1). The matched `AudioFormatSpec`'s channel/sample-rate
ranges gate pass-through; OGG_OPUS and MP3 are documented as restriction-free, WAV is bounded
conservatively (the exact multi-channel ceiling is unpublished — it is no longer indirectly bounded
by a decoded-buffer cap, which moved out of `lib/stt` per the §5 accepted gap; a >2-channel source
that routes to transcode is rejected by `EncoderError`).

### 7.1 Authentication and request

Every submit, operation poll, result fetch, and delete request includes:

```text
Authorization: Api-Key <api-key>
x-folder-id: <folder-id>
```

The service account needs `ai.speechkit-stt.user`. Inline v1 does not require Object Storage roles.
**Never log credentials, authorization headers, base64 audio, complete provider bodies, or complete
transcripts.**

Submit exactly:

```text
POST https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync
```

Protobuf-JSON body:

```json
{
  "content": "<base64 audio bytes (WAV / OGG_OPUS / MP3)>",
  "recognition_model": {
    "model": "general",
    "audio_format": {
      "container_audio": {
        "container_audio_type": "WAV"
      }
    },
    "language_restriction": {
      "restriction_type": "WHITELIST",
      "language_code": ["ru-RU"]
    },
    "text_normalization": {
      "literature_text": true
    }
  }
}
```

`model` and BCP-47 language are provider config. Do **not** send v2-like `folderId`, `audioFormat`,
`recognizeSpec`, `languageCode`, or `autoLanguage` body fields. The `container_audio.container_audio_type`
field is set **dynamically** from `audio.container.toYandexSpeechKit()` (one of `WAV`, `OGG_OPUS`,
`MP3` — the protobuf-JSON wire labels produced by the `STTAudioContainerType` method, §4) — it is
no longer hard-coded to `WAV` and is not read off `ExtractedAudio.container.value` (those values are
the lowercase internal labels, not the wire labels). SpeechKit accepts OGG_OPUS and MP3 "without any
audio file quality and header restrictions" (verified against the v3 proto's `ContainerAudio.ContainerAudioType`
enum, which has exactly these three members; there is no AIFF/AC3/FLAC). The async API documents a **60 MB inline
request** limit, a **1 GB Object-Storage** upload limit (deferred in v1 per D8), a **4-hour** duration
ceiling, 500 async submissions/hour, and five operation polls/second. v1 uses the inline path only; the
conservative service-side caps (§8.1) stay well below the 60 MB boundary. Quality-by-format is UNVERIFIED (see
§10(b)); the proven win is payload size/traffic (compressed containers are far smaller than WAV).

### 7.2 Operation lifecycle

1. Parse the operation ID from submit.
2. Poll `GET https://operation.api.cloud.yandex.net/operations/{id}` until `done=true` or the
   180-second operation budget expires.
3. If the operation contains `error`, return `ERROR`; `done=true` does **not** contain the transcript.
4. Fetch recognition events separately with
   `GET https://stt.api.cloud.yandex.net/stt/v3/getRecognition` and query param `operation_id={id}`.
5. After a successful fetch and parse, best-effort
   `DELETE https://stt.api.cloud.yandex.net/stt/v3/deleteRecognition` with the same query parameter to
   reduce the default result retention. Cleanup failure logs a warning but **never** discards a
   successful transcript.

   > **Implementation note (delete-timing refinement).** The implementation runs the
   > best-effort DELETE in a `finally` block that covers the fetch — i.e. it runs **after the
   > fetch succeeded but before parse**, and also when the submit/poll path raised (no fetch
   > happened, but an operation was created). This is an intentional refinement of the
   > "after fetch" intent above, not a contradiction of it: the recognised bytes are already in
   > memory so the operation object is no longer needed for correctness regardless of parse
   > outcome; the DELETE is best-effort and idempotent (a redundant delete on an
   > already-deleted/erroring operation is a no-op); and parse cannot fail catastrophically
   > because the parser honours the never-raise guard (contract #2). Do **not** "fix" the
   > `finally`-based ordering to match a literal reading of "after a successful fetch **and**
   > parse" — the load-bearing comment at
   > [`lib/stt/providers/yandex_speechkit.py`](../../lib/stt/providers/yandex_speechkit.py)
   > (~lines 313–331) documents this. The intent (reduce retention; never discard a successful
   > transcript) is unchanged.

Use **one persistent `httpx.AsyncClient`** configured with the injected resolved `ProxyConfig`
(spread via `proxyConfig.toKwargs()`); the provider's own `aclose()` closes it (the integration layer
— the future `STTService` — owns calling `aclose()` during graceful shutdown after workers drain, §8;
there is no `STTManager` anymore). Resolve the proxy in the main/service layer via
`ProxyService.resolveProxy(sttConfig, "stt")`
([`internal/services/proxy/service.py:141`](../../internal/services/proxy/service.py)), then inject it.
Calling `ProxyConfig.fromServiceConfig()` directly inside `lib/stt` would bypass per-service proxy
lifecycle registration (parent §9).

### 7.3 Event parsing — `lib/stt/providers/yandex_events.py` (correction #2)

> **Live-wire known-unknown (load-bearing contract #4 — read before implementing or testing).**
> Per the live-wire known-unknown (§10(a)) and parent §13.3 gate-1, the `getRecognition` transport framing/content-type is
> **PROVISIONAL**. `yandex_events.py` is implemented per the provisional streaming-JSON spec below and
> **must be verified/adjusted by the parent §13.3 gate-1 smoke test before release.** Do **not**
> over-commit the parser shape in golden tests before that gate runs — golden fixtures should assert
> the parsing *logic* (event semantics) while treating framing as provisional until gate-1 captures the
> real wire shape.

`getRecognition` is server-streaming. Official REST examples show consecutive JSON event objects, not
one JSON document, but do not specify a stable wire framing/content-type contract. The provisional
parser reads streaming bytes up to `max-result-bytes`, decodes UTF-8 strictly, and parses consecutive
objects with `JSONDecoder.raw_decode`, skipping only whitespace between objects and rejecting other
garbage. Enforcing `max-result-bytes` here is the one surviving module-level cap inside `lib/stt`
(the result-body cap, enforced at module level by `yandex_events.py`); exceeding it yields
`PROTOCOL_ERROR`. (This is all that remains of the old "caps enforced at module level" contract #3 —
every `extractAudio` cap moved to `STTService` per §5/§8.1, and the transcript-char formatter cap was
deleted with `lib/stt/formatter.py` in the 2026-08-02 simplification; only the result-body cap
remains.)

Relevant events are under `result.final` and `result.finalRefinement.normalizedText`. For each final
event:

- **choose the first alternative** — alternatives are competing hypotheses, not separate segments;
- accept `startTimeMs`/`endTimeMs` as **decimal strings or integers** because protobuf JSON may encode
  `int64` as strings;
- preserve word text and millisecond ranges in memory (the `TranscriptionWord` tuple);
- use a matching `finalRefinement.finalIndex` to **replace** the raw final text with normalized text
  rather than emitting both;
- ignore non-final update events for persistence;
- **sort final segments by start time** before formatting.

If there are no non-empty final segments, return `NO_SPEECH`. The confidence field exists but is
documented as currently unused; do not build v1 behavior around it or assert it will always be zero.

### 7.4 Retry policy

- **Do not automatically retry submit `POST`.** A timeout can occur after Yandex has accepted a
  billable operation, and retrying without an operation ID can create duplicate cost.
- Operation-poll and result-fetch **`GET`s are idempotent** and may retry transient transport errors,
  429, and 5xx responses with bounded backoff inside the same 180-second budget. Do **not** retry
  authentication/validation 4xx responses. Deletion is best-effort. Respect `Retry-After` when valid
  and keep aggregate poll frequency below the vendor quota.
- **Each `getRecognition` attempt is atomic**: buffer and parse it independently, commit no segments
  from a partial/failed stream, and discard that attempt before retrying from the beginning. Otherwise
  a retried stream can duplicate final events. The 180-second operation budget starts immediately
  before submit and includes submit, polling, and the successful result fetch; best-effort deletion
  does not invalidate a result when the budget is exhausted.

### 7.5 SDK decision

`yandex-ai-studio-sdk==0.22.0` is already pinned
([`requirements.direct.txt`](../../requirements.direct.txt)) and has documented deferred SpeechKit STT
support (`run_deferred` and `get_recognition_result`) — a credible fallback, unlike the stale claim that
no usable SDK surface exists. D6 still selects raw `httpx` for explicit wire, streaming-cap, proxy,
retry, and cleanup control. Do **not** add the older `yandex-cloud-ml-sdk` package (parent §2 D6, §15).

## 8. Provider as direct entry point

> The section heading is retained (numbering unchanged) but its content is rewritten: the
> pre-simplification design described an `STTManager` class in `lib/stt/manager.py`. That class and
> file are **deleted**. There is no manager.

The post-simplification shape dropped the `STTManager` indirection entirely. There is no
`lib/stt/manager.py`, and no manager selects the configured provider. The integration layer (the
future `STTService`, per [`stt-next-steps.md`](./stt-next-steps.md) §3.1) **holds the single configured
provider directly** — today that is `YandexSpeechKitProvider`, constructed once at startup with its
already-resolved `ProxyConfig` (§1 seam #1) and held as a singleton attribute on the service.

What the deleted manager used to own moves to the service:

- **`aclose()` ownership** — the service calls `provider.aclose()` during graceful shutdown, **after**
  in-flight STT workers have drained (parent §11.3). Best-effort, must not block shutdown. (The deleted
  manager's defensiveness — closing the HTTP client after the queue drained — moves here verbatim.)
- **Cap ownership** — the service owns all caps (source bytes, duration, inline payload); the
  decoded-buffer cap is intentionally absent (§5 accepted gap). See §8.1.

**`AbstractSTTProvider` surface** (§4, §7): four members — the ordered `supportedInputFormats()`
**method** (consumed by `audio.py`), the async `transcribe(ExtractedAudio)` entry (never-raise), the
concrete async `stt(data: bytes)` never-raise entry defined on the base itself (wraps
`extractAudio` + `transcribe`), and `aclose()`. The integration layer's convenience entry is `stt(data)`
(it never raises and returns a `TranscriptionResult` for every outcome).

The concrete `YandexSpeechKitProvider.transcribe()` takes `ExtractedAudio` only — **no** unused
`audioFormat`, `withTimestamps`, or chat-settings arguments (the container travels inside
`ExtractedAudio.container`, not as a separate argument). Caps (operation/request timeouts, poll delays,
result-byte cap, retry budget) and config (credentials, model, language, proxy) are supplied at
construction, not on `transcribe`. Expected provider/transport/protocol failures return
`TranscriptionResult(status=ERROR, errorCode=...)`; the constructor may raise `ValueError` on startup
configuration validation when STT is enabled (the only permitted raise site).

## 9. Test matrix slice (lib/stt only)

All tests live under `tests/lib/stt/` mirroring source paths
(`tests/lib/stt/test_abstract.py`, `tests/lib/stt/test_audio.py`, `tests/lib/stt/test_formatter.py`,
`tests/lib/stt/test_models.py`, `tests/lib/stt/providers/test_yandex_speechkit.py`,
`tests/lib/stt/providers/test_yandex_events.py`). `async def test_...` with **no** decorator
(`asyncio_mode = "auto"`). **Mock transport only — no real network** in automated tests. (`lib/stt`
itself has no singletons, so no singleton-reset fixtures are needed.) This section is the authoritative
lib/stt test matrix; parent §13.2 summarizes and references it.

**Models and exceptions**

- Enum membership and exact string values for `STTResultStatus`, `STTErrorCode` (the **eight** shared
  failure-category members — `AUDIO_TOO_LARGE` is gone), and `STTAudioContainerType` (lowercase values).
- `STTAudioContainerType.toYandexSpeechKit()` wire-label mapping (`wav` → `WAV`, `ogg-opus` →
  `OGG_OPUS`, `mp3` → `MP3`).
- Frozen/slot record construction and immutability; `TranscriptionResult.errorCode` default.
- The typed extraction-exception taxonomy (3 subclasses): the 1:1 (and shared) exception →
  `STTErrorCode` mapping and the `isinstance` relationship to `STTExtractionError`.

**Transcript formatter — MOVED OUT (see §6)**

> The bullets below described the **deleted** `lib/stt/formatter.py` (header +
> `[HH:MM:SS]` lines, XML escaping, `[No speech detected]` sentinel, deterministic
> `maxTranscriptChars` truncation). The 2026-08-02 simplification deleted that
> module: the formatter moved to
> [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py)
> and is now **thin** — no header, no XML escaping, no truncation, no
> `max-transcript-chars` parameter, no sentinel (`NO_SPEECH` → `""`). Those
> bullets are retained as the historical record of what `lib/stt` used to test;
> there are **no** formatter tests under `tests/lib/stt/` anymore (the
> `test_formatter.py` referenced in §9 was deleted with the module).

- Basic one/multi-segment formatting (header + `[HH:MM:SS] text` lines); timestamp zero-padding and
  hours ≥ 2 digits.
- Ordering: the formatter does NOT re-sort (segments emitted in given order).
- XML escaping with the `&`-first ordering; skipping whitespace-only segments.
- The `[No speech detected]` sentinel (no header prepended); under-cap results returned unchanged.
- Deterministic head/tail truncation to an EXACT character boundary, including the marker digit-width
  fixed-point (crossing powers of 10); the header is counted inside the cap (output never exceeds it).
- Int and decimal-string timestamp inputs; malformed-timestamp rejection (event-parsing side, §7.3).

**Abstract provider (`stt()` never-raise surface — load-bearing)**

- `AbstractSTTProvider` cannot be instantiated directly (abstract members present).
- A concrete stub implementing all three abstract members (`supportedInputFormats`, `transcribe`,
  `aclose`) constructs and its surface behaves per the contract; `transcribe` / `aclose` are
  coroutines.
- **`stt()` never raises:** a typed extraction failure (`NoAudioTrackError`) → ERROR with its
  `errorCode`; an unexpected extraction exception → ERROR PROVIDER_ERROR; a successful extraction
  delegates to `transcribe` and returns its result.
- **Regression: `stt()` covers the `transcribe` call too** — a provider whose `transcribe` raises an
  unexpected exception is caught by the defense-in-depth branch (logged + PROVIDER_ERROR) rather than
  escaping. (Pre-fix, `transcribe` sat after the try/except and a raise escaped `stt`.)

**PyAV extraction**

- Voice/audio/video fixtures; mono/stereo and different source rates.
- No audio track, corrupt/truncated input, decoder/muxer failure.
- Resampler and encoder flush preserve tail samples.
- Input/output containers close on success **and** every failure path (including cancellation) via a
  close-tracking proxy.
- **Container-only negotiation:**
  - Pass-through of OGG_OPUS and MP3 source (Telegram `VOICE`/`AUDIO` shapes) — no transcode,
    channels and rate preserved, `container_audio_type` set from `audio.container.toYandexSpeechKit()`.
  - Transcode of an unsupported source container (e.g. AAC/FLAC, or a Vorbis-in-OGG source that must
    not be mislabelled OGG_OPUS) → OGG_OPUS (the provider's first supported compressed format).
  - Out-of-spec supported container (channel/rate outside the matched `AudioFormatSpec`) routes to
    transcode rather than pass-through.
  - Channel preservation: a stereo source stays stereo through **both** the pass-through and transcode
    paths (no downmix).
  - `>2`-channel source on the transcode path → `EncoderError` (opus/mp3 ceiling + never-downmix).
  - No compressed transcode target available → `EncoderError`.
- (There are **no** source-byte / decoded-buffer / duration / inline-payload cap tests in `lib/stt` —
  those caps moved to `STTService` and are exercised in the integration test suite, not here. See §8.1.
  Likewise there are no `STTManager` tests — the class is deleted.)

**Yandex golden HTTP**

- Exact submit URL/body/headers (incl. dynamic `container_audio.container_audio_type` from
  `audio.container.toYandexSpeechKit()`); operation polling; separate result fetch; best-effort delete.
- Concatenated/whitespace-delimited result events and split HTTP chunks.
- Multiple finals, top-alternative selection, out-of-order finals, `finalRefinement` replacement by
  `finalIndex`, and no duplicate text.
- `int64` times as strings and integers; no speech.
- Operation error, authentication error, 429/5xx, timeout, malformed JSON, trailing garbage,
  result-body cap, and cleanup failure.
- **Assert submit is never blindly retried; assert only idempotent requests use bounded retry.**
- **Assert the `finally`-based delete ordering** (§7.2): the DELETE runs after fetch succeeded but
  before parse, and also when submit/poll raised, without invalidating a successful transcript.

> Per load-bearing contract #4, golden HTTP tests assert the parsing/wire **logic**; the `getRecognition`
> framing/content-type assertions stay provisional until parent §13.3 gate-1 captures the real shape.

## 10. Inherited release gates & open questions

**(a) Live-wire known-unknown (load-bearing contract #4).** The `getRecognition` transport
framing/content-type is **PROVISIONAL** (§7.3; parent §13.3 gate-1). `yandex_events.py` is implemented
per the provisional streaming-JSON spec and **must be verified/adjusted by the gate-1 smoke test
before release.** Do not treat the parser shape as fixed until that gate runs.

**(b) Manual gates from parent §13.3 that block *enabling*/releasing STT but NOT lib/stt
code-completion.** These require credentials or platform/runtime behavior and cannot be proven by
static review (full detail in parent §13.3):

1. **Real recognition capture** — run one short real recognition and capture only redacted structural
   output to confirm submit, operation, event framing, refinement ordering, and delete. (This **is**
   the live-wire gate referenced in (a).)
2. **Model confirmation** — confirm whether `general` or `deferred-general` is the appropriate
   production model; retain the configured model either way.
3. **Inline-limit semantics** — confirm the provider's inline-limit semantics (60 MB inline vs. base64
   expansion). The product stays at the conservative 40 MiB inline-payload default even if the vendor
   accepts more.
4. **10-minute end-to-end latency** — test representative 10-minute media end to end; if p95
   processing does not complete within the existing 300-second media poll, reduce default duration or
   redesign originating-turn waiting before release (never attach an unbounded worker task).
5. **Peak RSS** — measure peak RSS and CPU with two max-size (1 GiB) source files and worst-case decoded output
   on deployment-equivalent hardware, including enabled attachment storage. ⚠️ Decoded memory is now
   **unbounded in `lib/stt`** (§5 accepted gap) — the service's source (`max-source-bytes`, currently 1 GiB)
   + duration caps bound it indirectly; measure the real spike and reduce source/duration/concurrency defaults if the deployment
   memory budget cannot absorb it (see [`stt-next-steps.md`](./stt-next-steps.md) §5).
6. **Graceful shutdown** — exercise graceful shutdown during a maximum-size decode and verify the
   deployment supervisor's external hard-kill grace policy for a simulated native hang.
7. **`make ci` Alpine-wheel proof** — run [`make ci`](../../AGENTS.md) to prove the pinned PyAV wheel
   works in the Alpine container.
8. **Encoder availability** — confirm `libopus` and `libmp3lame` are present in the pinned
   `av==18.0.0` wheel on every target platform (the transcode-to-OGG_OPUS/MP3 path depends on them;
   §2). Almost certainly present in published manylinux/musllinux/macOS artifacts, but verify before
   release.
9. **Quality-by-format smoke test (UNVERIFIED)** — the docs are silent on whether OGG_OPUS/MP3 vs.
   WAV changes recognition quality, and on internal resampling. Run one short clip recognized in
   pass-through (OGG_OPUS) and the same clip transcoded, and compare. The proven win is size/traffic,
   not quality; treat any quality difference as an observation, never a design assumption.

No secrets, full audio, full transcripts, or authorization headers may be stored in smoke-test
artifacts.

**(c) Code-complete vs. release.** These gates are documented in the parent. Per parent §16/§13.3,
**automated `lib/stt` code can be complete and default-off while these gates remain open**: STT ships
behind `[stt].enabled = false` and the per-chat `TRANSCRIBE_MEDIA` setting (both default off), so a
green lib/stt implementation does not enable any billable behavior until an operator turns it on after
the gates pass.

---

### Inherited limits table (parent §8.1), annotated by cap-ownership

All cap **values** are owned by `STTService` (config-owned); `lib/stt` reads no `[stt]` config and
enforces no source/duration/inline/decoded caps (§5). The **Enforced by** column states where the
actual check is applied — inside a `lib/stt` module, or entirely `STTService`-side (the value never
reaches `lib/stt`, or reaches it unbounded).

| Guard | Default | Enforced by (cap ownership) |
|---|---:|---|
| Source container | 1,073,741,824 bytes (1 GiB; `max-source-bytes`) | **STTService** — bounds the platform media download before `extractAudio` is called; the bytes that reach `lib/stt` are already bounded. (The §5 decoded-memory gap means a 1 GiB compressed source can still decode to multiple GB — `lib/stt` does not re-check.) User-configurable; currently defaults to 1 GiB per the accepted residual Max-unbounded-download risk (user decision 2026-08-03; Telegram is platform-capped ~20 MB by the bot API). |
| Decoded buffer | (removed) | **gone** — `lib/stt` does not bound decoded PCM (§5 accepted gap). The service's source + duration caps bound it indirectly. If parent §13.3 gate-5 fails, restore a decoded-buffer cap inside `extractAudio`. |
| Inline payload | 41,943,040 bytes (40 MiB; `maxInlineBytes`) | **STTService** — bounds the *source* before it reaches `lib/stt`; `lib/stt` no longer routes pass-through vs. transcode on payload size (container-only routing, §5). A large supported container is now sent inline. The service keeps the conservative 40 MiB default so base64-expanded requests stay under the 60 MB vendor limit. |
| Decoded duration | 600 seconds | **STTService** — bounds admission before `extractAudio` is called; `lib/stt` no longer rejects or stop-at-caps on duration. Bounded upstream by the 300 s media-poll (parent §13.3 gate-4); do not relax toward the 4 h vendor ceiling. |
| Result body | 5,242,880 bytes (5 MiB) | **lib/stt (`yandex_events.py`)** — streaming byte cap before parse (constructor-supplied `maxResultBytes`). |
| Persisted transcript | (removed) | **gone** — the 2026-08-02 simplification deleted `lib/stt/formatter.py` and its `maxTranscriptChars` parameter. The thin formatter now lives at [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py) and does not truncate; there is no persisted-transcript cap. |
| Global workers | 2 | **STTService** — semaphore; never reaches `lib/stt`. |
| Admission wait | 20 seconds | **STTService** — admission; never reaches `lib/stt`. |
| HTTP request | 30 seconds | **lib/stt (Yandex provider)** — per `httpx` request; value passed in at construction. |
| SpeechKit operation | 180 seconds | **lib/stt (Yandex provider)** — operation budget across submit/poll/get; value passed in at construction. |
| Poll interval | 2 s initial, 10 s max | **lib/stt (Yandex provider)** — poll loop; value passed in at construction. |

**Vendor ceilings vs. v1 defaults (annotated).** SpeechKit's async ceilings are: **60 MB inline
request** (used by v1), **1 GB Object-Storage upload** (deferred in v1 per D8), and a **4-hour
duration** ceiling. v1 defaults stay conservative on all three: the service's inline-payload cap
(40 MiB) keeps base64-expanded requests well under 60 MB; Object-Storage is not used; the duration
default (600 s) stays far below 4 h and is additionally bounded by the 300 s media-poll. The vendor
ceiling is not a safe application default. (The pre-simplification design listed `lib/stt`-enforced
source/decoded/inline/duration rows; those are all **STTService-owned** now per §5.)

All values are validated as positive and operator-configurable (parent §8.1, §11.2). Release testing
must measure peak RSS with two maximum-size workers (parent §13.3 gate-5); because decoded memory is
now unbounded in `lib/stt` (§5), reduce source/duration/concurrency defaults if the deployment memory
budget cannot absorb the decoded-memory spike (see [`stt-next-steps.md`](./stt-next-steps.md) §5).

### Alternatives relevant to lib/stt (parent §15, carried over as-is)

| Alternative | Decision |
|---|---|
| Use the existing Yandex AI Studio SDK | Credible fallback, but D6 keeps raw `httpx` for exact streaming, caps, retry, proxy, and delete control. |
| Shell out to `ffmpeg` | Rejected by D3. Pinned PyAV gives an in-process API and supported binary wheels, with source-build caveats. |
| Use the full 60 MB inline / 1 GB Object-Storage / 4-hour vendor limits | Rejected as unsafe defaults — source, decoded audio, base64, JSON, and provider results create multiple memory copies and long user-path latency. (Object-Storage is also deferred in v1 per D8.) |
