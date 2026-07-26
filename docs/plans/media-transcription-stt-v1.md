# Plan: Media Transcription (Speech-to-Text) v1

Status: **APPROVED** — design decisions resolved; ready for implementation
Date: 2026-07-27
Owner: TBD
Companion docs: [`docs/llm/architecture.md`](../llm/architecture.md), [`docs/llm/services.md`](../llm/services.md), [`docs/llm/libraries.md`](../llm/libraries.md), [`docs/llm/configuration.md`](../llm/configuration.md), [`docs/llm/handlers.md`](../llm/handlers.md)

> All design decisions in §4 were ratified by the user on 2026-07-27. This
> is a **plan document only** — research/design artefact. No production code
> is changed by this file. Implementation is executed against the phasing in
> §7 by dispatching `software-developer` (code) and `docs-writer` (doc sync)
> tasks; the final documentation pass must load the `update-project-docs`
> skill.

## Summary

Add Speech-to-Text for inbound media so the LLM can see audio/video content.
Scope: **VIDEO, VIDEO_NOTE, VOICE, AUDIO** — unified pipeline, one chat
setting, one provider. STT provider: **Yandex SpeechKit v3 async**
(`recognizeFileAsync`) — the only surface giving utterance-level ("replica")
timestamps plus word-level timestamps, which is the hard requirement. Audio
extraction from video containers via **PyAV** (no system ffmpeg install
required). Trigger: **chat-setting auto** mirroring the existing
`PARSE_ATTACHMENTS` image-parsing path — a new `TRANSCRIBE_MEDIA` chat
setting, default off, friend tier. Result: transcript stored as the
attachment's existing `description` column, which **auto-injects** into the
LLM message via the existing `updateMediaContent` → `formatForLLM` path —
**zero schema migration**.

Provider abstraction built now (`lib/stt/` mirroring `lib/ai/`) so swapping
to OpenAI Whisper / local Whisper / Azure later is a new provider file, not
a rewrite.

---

## 1. Goals & non-goals

### 1.1 Goals

1. **Make audio/video content visible to the LLM.** Today voice/audio/video
   messages are downloaded, content-addressed, and stored, but their content
   is never parsed — only images are. The LLM is blind to ~all audio media.
2. **Preserve replica boundaries with timestamps.** Each recognised
   utterance carries `[HH:MM:SS]` so the model (and users reading the
   transcript) can reason about temporal structure.
3. **Slot into the existing media pipeline with zero schema churn.** Reuse
   the `media_attachments.description` column + the existing auto-inject
   path (`updateMediaContent` → `formatForLLM`).
4. **Build the provider abstraction now.** `lib/stt/` mirrors `lib/ai/`:
   `AbstractSTTProvider` + `STTManager` + `YandexSpeechKitProvider`. Adding
   a second provider later (Whisper, local) is one new file.
5. **Cost-guarded by default.** Yandex STT is billed per second of audio.
   Per-chat rate limit + file-size/duration caps + default-off friend-tier
   gating limit the blast radius.
6. **Be reusable: no bot deps in `lib/stt/`.** Honours the
   [`lib/` no-bot-deps rule](../../AGENTS.md).

### 1.2 Non-goals (v1)

- **Object Storage input** (≤1 GB / 4 h audio via S3-compatible URI).
  v1 is **inline upload only (≤60 MB)**. Files over the inline cap return a
  clean error result. Object Storage requires extra infra (bucket + signed
  URLs) and is deferred to v1.5 if there's demand.
- **Speaker diarization.** SpeechKit v3 supports it but adds complexity.
  v1 assumes single-speaker audio. Multi-speaker videos are transcribed as
  a single stream.
- **Auto-language detection.** v1 is config-pinned (default `ru-RU`).
  SpeechKit supports auto-language; can flip a config flag later.
- **Word-level confidence scores.** v3 always returns `confidence = 0`;
  v2 returns confidence but lacks word timestamps. Trade-off deferred —
  neither is blocking.
- **Structured transcript persistence** (per-word JSON). v1 writes a
  formatted text string to `description`. The raw structured response is
  available in-memory (`TranscriptionResult.raw`) if we later add a column
  or repurpose `metadata` JSON.
- **Visible reply / document export of the transcript.** v1 is silent —
  the transcript reaches the user only via the model's response. A
  `/transcribe` reply-command or document export is a follow-up.
- **Sync (streaming) STT.** Async `recognizeFileAsync` only — it's the
  only surface giving timestamps + the higher size limit.

---

## 2. Current state (authoritative — from exploration)

### 2.1 Media pipeline today

| Concern | Location | Behaviour |
|---|---|---|
| Central media processing | [`internal/bot/common/handlers/base.py:1726-1930`](../../internal/bot/common/handlers/base.py) (`_processMediaV2`) | Downloads, content-addresses via `storeAttachment`, stores in `StorageService`, gates parsing on `PARSE_ATTACHMENTS`. **Image-only parsing** — non-image media gets `MediaStatus.NEW` and is never analysed. |
| Image parsing template | [`internal/bot/common/handlers/base.py:1316-1367`](../../internal/bot/common/handlers/base.py) (`_parseImage`) | Builds `[ModelMessage, ModelImageMessage]`, calls `llmService.generateText`, writes `description` + `status=DONE` on success, `status=FAILED` on exception. **The structural template for `_transcribeMedia` (§3.11).** |
| Auto-inject hook | [`internal/bot/models/ensured_message.py:973-998`](../../internal/bot/models/ensured_message.py) (`updateMediaContent`) | Awaits `processingInfo.awaitResult()`, polls DB via `_awaitMedia`, reads `mediaAttachment["description"]` into `media.content` (per-item) and `self.mediaContent` + `self.mediaPrompt` (primary). |
| LLM formatting | [`internal/bot/models/ensured_message.py:1179-1185`](../../internal/bot/models/ensured_message.py) (`formatForLLM`, TEXT branch) | Wraps as `<media-description>{mediaContent}</media-description>\n\n{messageText}`. JSON branch (`:1159-1177`) puts it under `"mediaDescription"`. **Conclusion: writing transcript to `description` = zero-touch auto-inject into LLM context.** |
| Media await budget | [`internal/bot/models/ensured_message.py:1010-1058`](../../internal/bot/models/ensured_message.py) (`_awaitMedia`) | Polls DB up to `MAX_MEDIA_AWAIT_SECS`, match on status: PENDING → sleep `MEDIA_AWAIT_DELAY`, DONE → return. **Risk for long videos — see §9 R2.** |
| Attachment download | [`internal/bot/common/bot.py:1018-1040`](../../internal/bot/common/bot.py) (`TheBot.downloadAttachment`) | Telegram: `tgBot.get_file().download_as_bytearray()`. Max: `file_id`-via-`getFile` only works <20 MB (Telegram API limit). Max: raw `httpx.get(url).content`. **No size guard before download.** |
| Max media routing | [`internal/bot/common/handlers/base.py:1604-1724`](../../internal/bot/common/handlers/base.py) (`processMaxMedia`) | Dispatches by attachment type. Audio attachments (`:1693-1707`) ARE downloaded/stored but never parsed. |

### 2.2 `MessageType` enum coverage

[`internal/models/shared_enums.py:34`](../../internal/models/shared_enums.py) — `MessageType` StrEnum already includes `AUDIO`, `VOICE:77`, `VIDEO`, `VIDEO_NOTE`. All four are routed through `_processMediaV2` today; all four hit the non-image fallthrough at `base.py:1892-1901` and exit with `MediaStatus.NEW`.

### 2.3 `media_attachments` schema (no change needed)

[`migration_013_remove_timestamp_defaults.py:268-281`](../../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py) — columns: `file_unique_id TEXT PRIMARY KEY`, `file_id TEXT`, `file_size INTEGER`, `media_type TEXT NOT NULL`, `metadata TEXT NOT NULL` (JSON), `status TEXT NOT NULL DEFAULT 'pending'`, `mime_type TEXT`, `local_url TEXT`, `prompt TEXT`, `description TEXT`, `created_at TIMESTAMP NOT NULL`, `updated_at TIMESTAMP NOT NULL`. No AUTOINCREMENT, no DEFAULT CURRENT_TIMESTAMP (per SQL portability).

**The `description` column is the storage target.** TypedDict at [`internal/database/models.py:232-258`](../../internal/database/models.py) (`MediaAttachmentDict`); `MediaStatus` StrEnum (`NEW`/`PENDING`/`DONE`/`FAILED`) at `:15-25`. `MediaAttachmentsRepository.updateMediaAttachment` ([`internal/database/repositories/media_attachments.py:180`](../../internal/database/repositories/media_attachments.py)) accepts `status`/`description`/`metadata`/etc. via dynamic UPDATE — already supports our write shape.

### 2.4 Existing Yandex integration patterns

| Pattern | File | What to copy |
|---|---|---|
| Raw httpx + Api-Key auth + never-raise | [`lib/yandex_search/client.py:317-411`](../../lib/yandex_search/client.py) (`YandexSearchClient._makeRequest`) | `async with httpx.AsyncClient(**proxyConfig.toKwargs(), timeout=...)` → POST → catches `httpx.TimeoutException`/`httpx.RequestError`/`json.JSONDecodeError`/`Exception`, logs, returns `None`. Auth header `Authorization: Api-Key {apiKey}` or `Bearer {iamToken}` (`:353-360`). **The exact template for `YandexSpeechKitProvider.transcribe`.** |
| Provider registry (LLM) | [`lib/ai/manager.py:49-269`](../../lib/ai/manager.py) (`LLMManager`) | Hardcoded `type → class` map at `:118-124`; `_initProviders` reads `config["providers"]`. **The structural template for `STTManager`.** |
| Singleton service wiring | [`internal/services/llm/service.py:145`](../../internal/services/llm/service.py) (`LLMService`) | Thread-safe singleton (`:163-205`), `llmManager` injected via `injectLLMManager` (`:207-216`) at `main.py:95`. **The structural template for `STTService`.** |
| Standalone-service config | [`configs/00-defaults/00-config.toml:146-178`](../../configs/00-defaults/00-config.toml) (`[yandex-search]`) + `ConfigManager.getYandexSearchConfig()` at [`internal/config/manager.py:429-443`](../../internal/config/manager.py) | Top-level TOML section + `ConfigManager.getXxxConfig()` accessor. **The exact template for `[stt]`.** |
| Proxy resolution | [`lib/proxy/__init__.py`](../../lib/proxy/__init__.py) | `ProxyConfig.fromServiceConfig(data)` (`:318-337`) reads `use-proxy` + `proxy`. `ProxyConfig.toKwargs(verify=...)` (`:433-486`) returns `ProxyKwargs` TypedDict spreading into `httpx.AsyncClient(**kwargs)`. SOCKS5 via optional `httpx-socks[asyncio]` with `_HTTPX_SOCKS_AVAILABLE` guard. |

Env vars already in repo: `YC_FOLDER_ID`, `YC_API_KEY`, `YC_IAM_TOKEN`. The `[stt]` config reuses `YC_API_KEY` + `YC_FOLDER_ID` — no new env vars required.

### 2.5 What does NOT exist

- **No STT / ASR / Whisper / SpeechKit / ffmpeg code anywhere.** Grep for `transcri|whisper|speech.to.text|recognize|asr|stt|ffmpeg` across `internal/` and `lib/` returns nothing relevant.
- **No `tempfile` convention in bot code.** Media bytes stay in memory (`bytes`/`bytearray`) throughout the pipeline. `tempfile`/`shutil`/`os.remove` appear only in `lib/sandbox/` (Docker workspace), `lib/bayes_filter` training, and tests.
- **Max's `AudioAttachment.transcription` field is unused.** [`lib/max_bot/models/attachment.py:340-386`](../../lib/max_bot/models/attachment.py) has `transcription: Optional[str]` (`:370, :384`) populated from the Max API — the bot never reads or sets it. (Out of scope for v1; mentioning for completeness.)

### 2.6 Chat-settings four-site rule

Per the [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md) skill, every new chat setting must change four sites together (CRITICAL lesson from `docs/llm/tasks.md` §4.1):

1. `ChatSettingsKey` StrEnum in [`internal/bot/models/chat_settings.py:255`](../../internal/bot/models/chat_settings.py) — UPPER_CASE name ↔ kebab-case string value + docstring.
2. `_chatSettingsInfo` dict (`chat_settings.py:559`) entry as **dict literal** TypedDict `ChatSettingsInfoValue`: `{type, short, long, page}`. `type ∈ {STRING/BOOL/INT/FLOAT/MODEL/IMAGE_MODEL}`. `page ∈ {STANDARD/EXTENDED/SPAM/LLM_MODELS/LLM_PROMPTS/LLM_PAID/PAID/FRIEND/BOT_OWNER/BOT_OWNER_SYSTEM}`.
3. Default in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) under `[bot.defaults]`, kebab-case key.
4. Consumer reads `settings[KEY].toBool()/.toStr()/.toInt()/.toFloat()/.toList()/.toModel()` — **NOT tuple indexing** (handler layer returns `ChatSettingsValue` objects, not the DB-repo `(value, updatedBy)` tuple shape).

---

## 3. Target state

### 3.1 Layering — mirror `lib/ai/` + `internal/services/llm/`

```text
lib/stt/                              # provider-agnostic, no bot deps
  __init__.py                         # public re-exports
  abstract.py                         # AbstractSTTProvider
  models.py                           # TranscriptionResult, TranscriptionAlternative, TranscriptionWord, STTResultStatus, formatTranscriptForLLM
  manager.py                          # STTManager — provider registry by name
  audio.py                            # extractAudio(videoBytes, *) -> bytes  (PyAV wrapper)
  providers/
    __init__.py
    base.py                           # BaseSTTProvider (httpx client + proxy init, aclose)
    yandex_speechkit_provider.py      # YandexSpeechKitProvider (v3 async, raw httpx)

internal/services/stt/               # singleton wiring to bot
  __init__.py
  service.py                          # STTService singleton, injectSTTManager, transcribe()

internal/bot/common/handlers/base.py # extend _processMediaV2 + add _transcribeMedia

configs/00-defaults/
  stt.toml                            # new [stt] section
  bot-defaults.toml                   # new transcribe-media = false default
```

### 3.2 Data flow

```mermaid
sequenceDiagram
    participant Tg as Telegram/Max
    participant Bot as TheBot
    participant Proc as _processMediaV2
    participant AV as lib/stt/audio.py
    participant STT as STTService
    manager STTM as STTManager
    participant SK as SpeechKit v3
    participant DB as media_attachments
    participant LLM as LLMService

    Tg->>Bot: video/voice/audio message
    Bot->>Proc: processMedia(type=VIDEO)
    Proc->>Proc: check TRANSCRIBE_MEDIA chat setting
    alt setting off OR not audio/video type
        Proc->>DB: status=DONE (skip parsing)
    else setting on
        Proc->>Proc: download bytes (existing path)
        Proc->>AV: extractAudio(mediaData)
        AV-->>Proc: mono 16kHz LINEAR16_PCM bytes
        Proc->>DB: status=PENDING
        Proc->>STT: transcribe(audioBytes, chatId, chatSettings) [async task]
        STT->>STT: rateLimit + size/duration guard
        STT->>STTM: getProvider()
        STT->>SK: POST recognizeFileAsync (inline, <=60MB)
        SK-->>STT: operationId
        loop poll until DONE
            STT->>SK: GET operation status
            SK-->>STT: DONE + result
        end
        STT->>STT: formatTranscriptForLLM(result)
        STT->>DB: description=transcript, status=DONE
    end
    Note over LLM: later — handler calls formatForLLM
    LLM->>DB: updateMediaContent reads description
    LLM->>LLM: inject as <media-description>...</media-description>
```

### 3.3 `lib/stt/` package — public exports (`__init__.py`)

```python
"""Speech-to-Text provider-agnostic library.

Mirrors lib/ai/: provider registry + abstract provider. No bot deps.
"""
from .abstract import AbstractSTTProvider
from .audio import extractAudio, AV_AVAILABLE
from .manager import STTManager
from .models import (
    STTResultStatus,
    TranscriptionAlternative,
    TranscriptionResult,
    TranscriptionWord,
    formatTranscriptForLLM,
)

__all__ = [
    "AbstractSTTProvider",
    "AV_AVAILABLE",
    "STTManager",
    "STTResultStatus",
    "TranscriptionAlternative",
    "TranscriptionResult",
    "TranscriptionWord",
    "extractAudio",
    "formatTranscriptForLLM",
]
```

### 3.4 `AbstractSTTProvider` (`lib/stt/abstract.py`)

Minimal surface — STT providers don't have the sub-model layer LLM providers do (SpeechKit has recognition models but it's not a registry of dozens):

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .models import TranscriptionResult


class AbstractSTTProvider(ABC):
    """Base class for all STT providers.

    Concrete providers implement :meth:`transcribe`. The contract is
    **never-raise**: implementations catch all exceptions and return a
    result with ``status = STTResultStatus.ERROR``. An unhandled exception
    would abort the whole media-processing task, mirroring the contract
    in ``lib/yandex_search/client.py:_makeRequest``.
    """

    @abstractmethod
    async def transcribe(
        self,
        audioData: bytes,
        *,
        language: str = "ru-RU",
        withTimestamps: bool = True,
        audioFormat: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes.

        Args:
            audioData: Audio bytes in a format the provider accepts (default
                LINEAR16 PCM mono 16 kHz — see :func:`lib.stt.audio.extractAudio`).
            language: BCP-47 language code (e.g. ``"ru-RU"``, ``"en-US"``).
            withTimestamps: When True, the result includes per-word and
                per-utterance timestamps. When False, only the full text.
            audioFormat: Optional override for the audio format sent to the
                provider. ``None`` lets the provider pick its default.

        Returns:
            :class:`TranscriptionResult`. Never raises — failures land in
            ``status`` and ``error``.
        """
        ...

    async def aclose(self) -> None:
        """Release any held resources (HTTP clients, etc.).

        Default no-op. Override when the provider owns a persistent
        ``httpx.AsyncClient``.
        """
        return

    @classmethod
    def listRemoteModels(cls) -> Dict[str, Any]:
        """Optional: enumerate provider-side recognition models.

        Returns:
            Empty dict by default. Providers may override for diagnostics.
        """
        return {}
```

### 3.5 `TranscriptionResult` model (`lib/stt/models.py`)

`@dataclass(slots=True)` per repo convention (no pydantic). `StrEnum` for status:

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


class STTResultStatus(StrEnum):
    """Outcome of a transcription call."""

    FINAL = "final"        # recognition complete, alternatives populated
    ERROR = "error"        # never-raise contract surfaced a failure
    PARTIAL = "partial"    # provider returned partial result (reserved)


@dataclass(slots=True)
class TranscriptionWord:
    """A single recognised word with its time span.

    Attributes:
        text: The recognised word.
        startTimeMs: Start time in milliseconds from audio start.
        endTimeMs: End time in milliseconds from audio start.
    """

    text: str
    startTimeMs: int
    endTimeMs: int


@dataclass(slots=True)
class TranscriptionAlternative:
    """One recognised utterance ("replica").

    Attributes:
        text: The full utterance text.
        startTimeMs: Utterance start in milliseconds.
        endTimeMs: Utterance end in milliseconds.
        words: Optional word-level breakdown (empty when the provider
            doesn't return word timestamps or ``withTimestamps=False``).
    """

    text: str
    startTimeMs: int
    endTimeMs: int
    words: List[TranscriptionWord] = field(default_factory=list)


@dataclass(slots=True)
class TranscriptionResult:
    """Complete transcription outcome.

    Attributes:
        status: Outcome flag. Never raises; check this first.
        alternatives: Utterance-level results, ordered by ``startTimeMs``.
            Empty on error.
        raw: Full provider response (debugging/diagnostics). May be ``None``.
        error: Error message when ``status == ERROR``; ``None`` otherwise.
        elapsedTime: Wall-clock seconds spent in the provider call.
    """

    status: STTResultStatus
    alternatives: List[TranscriptionAlternative]
    raw: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    elapsedTime: float = 0.0


def formatTranscriptForLLM(result: TranscriptionResult) -> str:
    """Render a transcript as the string stored in ``media_attachments.description``.

    Format (one line per utterance):

        [HH:MM:SS] First replica text.
        [HH:MM:SS] Second replica text.

    Args:
        result: A successful transcription result (``status == FINAL``).

    Returns:
        The formatted transcript string. Empty string when ``alternatives``
        is empty.
    """
    lines: List[str] = []
    for alt in result.alternatives:
        totalSec = alt.startTimeMs // 1000
        hours = totalSec // 3600
        minutes = (totalSec % 3600) // 60
        seconds = totalSec % 60
        lines.append(f"[{hours:02d}:{minutes:02d}:{seconds:02d}] {alt.text}")
    return "\n".join(lines)
```

### 3.6 `YandexSpeechKitProvider` (`lib/stt/providers/yandex_speechkit_provider.py`)

Raw `httpx` hitting SpeechKit v3 async. **Not** the `yandex-cloud-ml-sdk` STT surface — research flagged that surface as underdocumented (§9 R1); raw httpx matches the proven [`lib/yandex_search/client.py`](../../lib/yandex_search/client.py) pattern.

- **Submit endpoint**: `POST https://stt.api.cloud.yandex.net/speech/v3/stt:recognize_file_async`
- **Poll endpoint**: `GET https://operation.api.cloud.yandex.net/operations/{operationId}`
- **Auth**: `Authorization: Api-Key {apiKey}` header (same `YC_API_KEY`).
- **Request body** (JSON):
  ```json
  {
    "folderId": "<folder-id>",
    "content": "<base64-encoded audio bytes>",
    "audioFormat": {"containerAudio": {"containerAudioType": "WAV"}},
    "recognizeSpec": {
      "languageCode": "ru-RU",
      "literatureText": true,
      "autoLanguage": false
    }
  }
  ```
  (Exact field shape must be verified against the live API before the provider is written — see §7 Step 5 and §9 R1.)
- **Polling**: exponential-ish backoff (`pollIntervalSec`, 2× each iteration up to ~15s cap) until operation `done: true` or `request-timeout` (default 300s) exceeded.
- **Mapping**: response `result.alternatives[]` → `TranscriptionAlternative`; `words[].startTime`/`endTime` (Google `Duration` protobuf strings like `"1.500s"`) → `startTimeMs`/`endTimeMs` via parse.
- **Never-raise**: `transcribe` catches `httpx.TimeoutException`, `httpx.RequestError`, `json.JSONDecodeError`, generic `Exception`; logs via `logging.getLogger(__name__)`; returns `TranscriptionResult(status=ERROR, error=str(e))`.

Structural skeleton:

```python
import base64
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from lib.proxy import ProxyConfig

from ..models import STTResultStatus, TranscriptionAlternative, TranscriptionResult, TranscriptionWord
from .base import BaseSTTProvider

logger = logging.getLogger(__name__)

_SUBMIT_ENDPOINT = "https://stt.api.cloud.yandex.net/speech/v3/stt:recognize_file_async"
_OPERATION_ENDPOINT = "https://operation.api.cloud.yandex.net/operations/{operationId}"


class YandexSpeechKitProvider(BaseSTTProvider):
    """Yandex SpeechKit v3 async STT provider (raw httpx)."""

    providerType: str = "yandex-speechkit"

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialise the provider from a [stt]-shaped config dict.

        Args:
            config: Merged [stt] config (keys: api-key, folder-id, language,
                request-timeout, poll-interval-sec, use-proxy, proxy).
        """
        self._apiKey: str = config["api-key"]
        self._folderId: str = config["folder-id"]
        self._language: str = config.get("language", "ru-RU")
        self._requestTimeout: float = float(config.get("request-timeout", 300))
        self._pollIntervalSec: float = float(config.get("poll-interval-sec", 3))
        self._proxyConfig: ProxyConfig = ProxyConfig.fromServiceConfig(config)

    async def transcribe(
        self,
        audioData: bytes,
        *,
        language: str = "ru-RU",
        withTimestamps: bool = True,
        audioFormat: Optional[str] = None,
    ) -> TranscriptionResult:
        """Submit audio to SpeechKit v3 async and poll for the result.

        Never raises — see class docstring.

        Args:
            audioData: Audio bytes (WAV container, mono 16 kHz LINEAR16 PCM
                — produced by :func:`lib.stt.audio.extractAudio`).
            language: Override for the provider default.
            withTimestamps: Kept for API symmetry; SpeechKit v3 always
                returns timestamps.
            audioFormat: Container format override (default ``"WAV"``).

        Returns:
            :class:`TranscriptionResult`.
        """
        started = time.monotonic()
        try:
            proxyKwargs = self._proxyConfig.toKwargs()
            async with httpx.AsyncClient(**proxyKwargs, timeout=self._requestTimeout) as client:
                operationId = await self._submit(client, audioData, language, audioFormat)
                if operationId is None:
                    return TranscriptionResult(
                        status=STTResultStatus.ERROR,
                        alternatives=[],
                        error="submit returned no operationId",
                        elapsedTime=time.monotonic() - started,
                    )
                rawResult = await self._poll(client, operationId)
                if rawResult is None:
                    return TranscriptionResult(
                        status=STTResultStatus.ERROR,
                        alternatives=[],
                        error="poll timed out or returned no result",
                        elapsedTime=time.monotonic() - started,
                    )
                alternatives = self._mapAlternatives(rawResult)
                return TranscriptionResult(
                    status=STTResultStatus.FINAL,
                    alternatives=alternatives,
                    raw=rawResult,
                    elapsedTime=time.monotonic() - started,
                )
        except (httpx.TimeoutException, httpx.RequestError) as e:
            logger.error("SpeechKit HTTP error: %s", e)
            return TranscriptionResult(
                status=STTResultStatus.ERROR, alternatives=[], error=str(e),
                elapsedTime=time.monotonic() - started,
            )
        except Exception as e:
            logger.exception("SpeechKit unexpected error")
            return TranscriptionResult(
                status=STTResultStatus.ERROR, alternatives=[], error=str(e),
                elapsedTime=time.monotonic() - started,
            )

    async def _submit(
        self, client: httpx.AsyncClient, audioData: bytes,
        language: str, audioFormat: Optional[str],
    ) -> Optional[str]:
        """POST the audio, return the operationId or None."""
        body = {
            "folderId": self._folderId,
            "content": base64.b64encode(audioData).decode("ascii"),
            "audioFormat": {"containerAudio": {"containerAudioType": audioFormat or "WAV"}},
            "recognizeSpec": {"languageCode": language, "literatureText": True},
        }
        headers = {"Authorization": f"Api-Key {self._apiKey}"}
        response = await client.post(_SUBMIT_ENDPOINT, headers=headers, json=body)
        if response.status_code != 200:
            logger.error("SpeechKit submit HTTP %s: %s", response.status_code, response.text)
            return None
        return response.json().get("id")

    async def _poll(
        self, client: httpx.AsyncClient, operationId: str,
    ) -> Optional[Dict[str, Any]]:
        """Poll the operation endpoint until done or timeout. Returns the raw response."""
        # Implementation: poll with self._pollIntervalSec, doubling up to 15s cap,
        # until response.json().get("done") is True or self._requestTimeout exceeded.
        ...

    @staticmethod
    def _mapAlternatives(
        raw: Dict[str, Any],
    ) -> list[TranscriptionAlternative]:
        """Map SpeechKit response -> TranscriptionAlternative list.

        Exact field names verified against the live API in §7 Step 5.
        SpeechKit v3 returns ``result.alternatives[].words[].startTime``/
        ``endTime`` as Google ``Duration`` strings (``"1.500s"``); parse to ms.
        """
        ...
```

### 3.7 Audio extraction — PyAV (`lib/stt/audio.py`)

PyAV (`pip install av`) bundles ffmpeg libs in the wheel — **no system ffmpeg install required**, deterministic across hosts. Works in the existing `./venv`. Optional-dependency guard per [`AGENTS.md`](../../AGENTS.md):

```python
"""Audio extraction wrapper around PyAV.

CPU-bound decode runs via :func:`asyncio.to_thread` to avoid blocking the
event loop. Bytes-in, bytes-out — no temp files.
"""
import asyncio
import io
import logging
from typing import Optional

try:
    import av
    _AV_AVAILABLE = True
except ImportError:
    _AV_AVAILABLE = False

logger = logging.getLogger(__name__)

# Defaults match SpeechKit v3 requirements: mono 16 kHz LINEAR16 PCM.
_DEFAULT_CODEC = "pcm_s16le"
_DEFAULT_SAMPLE_RATE = 16000
_DEFAULT_CHANNELS = 1


async def extractAudio(
    mediaData: bytes,
    *,
    targetCodec: str = _DEFAULT_CODEC,
    targetSampleRate: int = _DEFAULT_SAMPLE_RATE,
    targetChannels: int = _DEFAULT_CHANNELS,
) -> bytes:
    """Extract and transcode the audio track to mono 16 kHz LINEAR16 PCM bytes.

    Args:
        mediaData: Source container bytes (any format PyAV/ffmpeg supports:
            mp4, mkv, webm, mp3, ogg, opus, m4a, ...). The first audio
            stream is used.
        targetCodec: Output codec (default ``"pcm_s16le"`` = LINEAR16 PCM).
        targetSampleRate: Output sample rate in Hz (default 16000).
        targetChannels: Output channel count (default 1 = mono).

    Returns:
        WAV-container bytes ready for SpeechKit inline upload.

    Raises:
        RuntimeError: If PyAV is not installed (``_AV_AVAILABLE == False``)
            or the input has no decodable audio stream.
    """
    if not _AV_AVAILABLE:
        raise RuntimeError(
            "PyAV is not installed; cannot extract audio. "
            "Add `av` to requirements.direct.txt and re-run `make install`."
        )
    return await asyncio.to_thread(
        _extractAudioSync,
        mediaData, targetCodec, targetSampleRate, targetChannels,
    )


def _extractAudioSync(
    mediaData: bytes, codec: str, sampleRate: int, channels: int,
) -> bytes:
    """Synchronous PyAV demux + transcode. Runs in a worker thread.

    Opens the input container from an in-memory bytes buffer, finds the
    first audio stream, decodes all frames, resamples to the target
    channel/rate layout via a PyAV resampler, muxes into an in-memory
    WAV container, returns the bytes.
    """
    # Implementation outline:
    # input_ = av.open(io.BytesIO(mediaData))
    # audioStream = next(s for s in input_.streams if s.type == "audio")
    # outputBuffer = io.BytesIO()
    # output = av.open(outputBuffer, mode="w", format="wav")
    # outputStream = output.add_stream(codec, rate=sampleRate)
    # outputStream.layout = "mono" if channels == 1 else "stereo"
    # resampler = av.AudioResampler(format="s16", layout=channels, rate=sampleRate)
    # for frame in input_.decode(audioStream):
    #     frame = resampler.resample(frame)
    #     for f in frame:
    #         pkt = outputStream.encode(f)
    #         if pkt:
    #             output.mux(pkt)
    # pkt = outputStream.encode(None)
    # if pkt:
    #     output.mux(pkt)
    # output.close(); input_.close()
    # return outputBuffer.getvalue()
    ...
```

### 3.8 `[stt]` config section (`configs/00-defaults/stt.toml`)

Mirrors `[yandex-search]` ([`configs/00-defaults/00-config.toml:146-178`](../../configs/00-defaults/00-config.toml)):

```toml
[stt]
# Global kill switch. When false, STTService.transcribe returns ERROR
# immediately regardless of chat-level TRANSCRIBE_MEDIA setting.
enabled = false

# Provider registry key (matches lib/stt/ type map). Only one provider today.
provider = "yandex-speechkit"

# HTTP proxy reuse (same ProxyConfig shape as [yandex-search]).
use-proxy = false
# proxy = { ... }   # only when use-proxy = true

# Yandex auth — reuse env vars already in the repo.
api-key = "${YC_API_KEY}"
folder-id = "${YC_FOLDER_ID}"

# Recognition language (BCP-47). v1 is config-pinned (no auto-detect).
language = "ru-RU"

# Operation poll timeout in seconds. SpeechKit async typically completes
# within seconds for short clips; allow up to 5 min for ~hour-long audio.
request-timeout = 300

# Initial poll interval (seconds). Doubles each iteration up to a ~15s cap.
poll-interval-sec = 3

# Rate limiter queue name (existing RateLimiterManager infrastructure).
ratelimiter-queue = "stt"

# Cost guardrails — refuse to transcribe beyond these.
max-duration-sec = 3600      # 1 hour
max-file-size-mb = 100       # pre-extraction container size cap
```

`ConfigManager.getSTTConfig()` accessor at [`internal/config/manager.py`](../../internal/config/manager.py) — mirror `getYandexSearchConfig` (`:429-443`):

```python
def getSTTConfig(self) -> Dict[str, Any]:
    """Return the merged ``[stt]`` config section.

    Returns:
        The STT config dict, or an empty dict if the section is absent.
    """
    return self.get("stt", {})
```

### 3.9 `TRANSCRIBE_MEDIA` chat setting (four sites)

1. **`ChatSettingsKey`** in [`internal/bot/models/chat_settings.py:255`](../../internal/bot/models/chat_settings.py):
   ```python
   TRANSCRIBE_MEDIA = "transcribe-media"
   """When True, voice/audio/video messages are auto-transcribed via STT
   and the transcript is injected into the LLM context."""
   ```
2. **`_chatSettingsInfo`** entry (dict literal, same file):
   ```python
   ChatSettingsKey.TRANSCRIBE_MEDIA: {
       "type": ChatSettingsType.BOOL,
       "short": "Транскрибация голосовых/видео",
       "long": "Автоматически распознавать текст из голосовых сообщений, "
               "видео и аудио. Распознанный текст (с тайм-кодами) попадает "
               "в контекст модели. Платная функция Yandex SpeechKit.",
       "page": ChatSettingsPage.FRIEND,
   },
   ```
3. **Default** in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) under `[bot.defaults]`:
   ```toml
   transcribe-media = false
   ```
4. **Consumer**: `_processMediaV2` (§3.10) reads `chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()`.

### 3.10 `_processMediaV2` edits

Three precise edits to [`internal/bot/common/handlers/base.py:1726-1930`](../../internal/bot/common/handlers/base.py):

**Edit A** — widen the parsing gate at `base.py:1834-1841`:

```python
# Before:
if chatSettings[ChatSettingsKey.PARSE_ATTACHMENTS].toBool() and mediaType in [
    MessageType.IMAGE,
    MessageType.STICKER,
]:
    mediaStatus = MediaStatus.PENDING
else:
    mediaStatus = MediaStatus.DONE

# After:
parseImage = chatSettings[ChatSettingsKey.PARSE_ATTACHMENTS].toBool() and mediaType in [
    MessageType.IMAGE,
    MessageType.STICKER,
]
transcribeMedia = (
    chatSettings[ChatSettingsKey.TRANSCRIBE_MEDIA].toBool()
    and mediaType in [MessageType.AUDIO, MessageType.VOICE, MessageType.VIDEO, MessageType.VIDEO_NOTE]
)
if parseImage or transcribeMedia:
    mediaStatus = MediaStatus.PENDING
else:
    mediaStatus = MediaStatus.DONE
```

**Edit B** — widen the existing-attachment-status branch at `base.py:1809-1819` to also re-process audio/video when transcription is on. Mirror the existing image re-processing logic; only the `mediaType`/setting predicate changes.

**Edit C** — extend the fallthrough branch at `base.py:1892-1901` to dispatch audio/video to `_transcribeMedia` instead of skipping:

```python
# Before:
if mimeType.lower().startswith("image/"):
    ...
else:
    logger.warning(f"{ret.type}#{ret.id} is not an image, skipping parsing")
    ret.task = makeEmptyAsyncTask()
    await self.db.mediaAttachments.updateMediaAttachment(mediaId=ret.id, status=MediaStatus.NEW)
    return ret

# After:
if mimeType.lower().startswith("image/"):
    ...   # existing image path unchanged
elif _isTranscribable(mediaType, mimeType) and transcribeMedia:
    logger.debug(f"{ret.type}#{ret.id} is audio/video, transcribing")
    transcribeTask = asyncio.create_task(
        self._transcribeMedia(ensuredMessage, ret.id, mediaData)
    )
    ret.task = transcribeTask
    await self.queueService.addBackgroundTask(transcribeTask)
    return ret
else:
    logger.warning(f"{ret.type}#{ret.id} is not an image and transcription is off, skipping")
    ret.task = makeEmptyAsyncTask()
    await self.db.mediaAttachments.updateMediaAttachment(mediaId=ret.id, status=MediaStatus.NEW)
    return ret
```

Helper near the method:

```python
_TRANSCRIBABLE_TYPES = frozenset(
    {MessageType.AUDIO, MessageType.VOICE, MessageType.VIDEO, MessageType.VIDEO_NOTE}
)
_TRANSCRIBABLE_MIME_PREFIXES = ("audio/", "video/")


def _isTranscribable(mediaType: MessageType, mimeType: str) -> bool:
    """Check whether this media type/mime is a candidate for transcription.

    Args:
        mediaType: The MessageType of the attachment.
        mimeType: The detected MIME type (lowercased).

    Returns:
        True when the media is audio/video and can be fed to STT.
    """
    if mediaType not in _TRANSCRIBABLE_TYPES:
        return False
    return any(mimeType.lower().startswith(prefix) for prefix in _TRANSCRIBABLE_MIME_PREFIXES)
```

### 3.11 `_transcribeMedia` method

New method in [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py), placed near `_parseImage` (`:1316-1367`). Mirrors `_parseImage` structurally:

```python
async def _transcribeMedia(
    self, ensuredMessage: EnsuredMessage, fileUniqueId: str, mediaData: bytes,
) -> bool:
    """Transcribe audio/video bytes and store the transcript as the attachment description.

    Mirrors :meth:`_parseImage`: on success writes ``description`` +
    ``MediaStatus.DONE``; on failure writes ``MediaStatus.FAILED``. The
    description is then auto-injected into the LLM context via
    :meth:`EnsuredMessage.updateMediaContent`.

    Args:
        ensuredMessage: The message owning the attachment.
        fileUniqueId: The attachment's ``file_unique_id`` (primary key).
        mediaData: The downloaded media container bytes (video/audio).

    Returns:
        True on success, False on failure.
    """
    chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
    try:
        # Extract audio (PyAV) — raises RuntimeError if PyAV missing.
        audioBytes = await extractAudio(mediaData)
        sttService = STTService.getInstance()
        result = await sttService.transcribe(
            audioBytes,
            chatId=ensuredMessage.recipient.id,
            chatSettings=chatSettings,
        )
        if result.status != STTResultStatus.FINAL or not result.alternatives:
            raise RuntimeError(f"STT failed: status={result.status} error={result.error}")
        transcript = formatTranscriptForLLM(result)
        await self.db.mediaAttachments.updateMediaAttachment(
            mediaId=fileUniqueId, status=MediaStatus.DONE, description=transcript,
        )
        return True
    except Exception as e:
        logger.error("Failed to transcribe media %s: %s", fileUniqueId, e)
        await self.db.mediaAttachments.updateMediaAttachment(
            mediaId=fileUniqueId, status=MediaStatus.FAILED,
        )
        return False
```

### 3.12 `STTService` singleton (`internal/services/stt/service.py`)

Mirrors [`LLMService`](../../internal/services/llm/service.py) shape. Adds guardrails:

```python
"""STT service singleton — wires lib/stt/ to the bot.

Mirrors LLMService: thread-safe singleton, manager injected at startup,
public ``transcribe`` applies rate limiting + size/duration guardrails.
"""
import logging
from typing import Any, Dict, Optional

from lib.rate_limiter import RateLimiterManager
from lib.stt import STTManager, STTResultStatus, TranscriptionResult

logger = logging.getLogger(__name__)


class STTService:
    """Singleton service exposing STT to the bot layer.

    Attributes:
        sttManager: Injected at startup via :meth:`injectSTTManager`.
    """

    _instance: Optional["STTService"] = None

    def __new__(cls) -> "STTService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialised = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialised", False):
            return
        self._initialised = True
        self.sttManager: Optional[STTManager] = None
        self._rateLimiter: RateLimiterManager = RateLimiterManager.getInstance()
        self._globalSema = asyncio.Semaphore(4)  # §9 R7 — concurrent-storm guard

    @classmethod
    def getInstance(cls) -> "STTService":
        """Return the singleton."""
        return cls()

    def injectSTTManager(self, manager: STTManager) -> None:
        """Inject the STTManager (called once at startup in main.py).

        Args:
            manager: The initialised STTManager instance.
        """
        self.sttManager = manager

    async def transcribe(
        self,
        audioData: bytes,
        *,
        chatId: int,
        chatSettings: Dict[str, Any],
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio with rate limiting + size guardrails.

        Args:
            audioData: Audio bytes (mono 16 kHz LINEAR16 PCM WAV).
            chatId: The chat id (for rate-limit keying).
            chatSettings: The chat settings dict (unused in v1; reserved).
            language: Optional language override.

        Returns:
            :class:`TranscriptionResult`. Never raises.
        """
        if self.sttManager is None:
            return TranscriptionResult(
                status=STTResultStatus.ERROR, alternatives=[],
                error="STTService not initialised (sttManager is None)",
            )
        config = self.sttManager.config
        if not config.get("enabled", False):
            return TranscriptionResult(
                status=STTResultStatus.ERROR, alternatives=[],
                error="STT globally disabled ([stt].enabled = false)",
            )
        # Size guardrail (pre-extraction size; audioData is post-extraction,
        # so this is a sanity cap on the WAV we're about to upload).
        maxBytes = int(config.get("max-file-size-mb", 100)) * 1024 * 1024
        if len(audioData) > maxBytes:
            return TranscriptionResult(
                status=STTResultStatus.ERROR, alternatives=[],
                error=f"audio bytes ({len(audioData)}) exceed max-file-size-mb",
            )
        # Rate limit.
        queueName = config.get("ratelimiter-queue", "stt")
        allowed = await self._rateLimiter.acquire(queueName, key=str(chatId))
        if not allowed:
            return TranscriptionResult(
                status=STTResultStatus.ERROR, alternatives=[],
                error="rate limit exceeded",
            )
        # Global concurrency guard.
        async with self._globalSema:
            provider = self.sttManager.getProvider()
            lang = language or config.get("language", "ru-RU")
            return await provider.transcribe(audioData, language=lang)
```

### 3.13 `main.py` wiring

Mirror the `LLMManager` + `LLMService` wiring at [`main.py:91-95`](../../main.py):

```python
self.sttManager = STTManager(configManager.getSTTConfig())
STTService.getInstance().injectSTTManager(self.sttManager)
```

And `STTManager.aclose()` in the shutdown block at [`main.py:144-148`](../../main.py):

```python
await self.sttManager.aclose()
```

`STTManager.aclose()` iterates registered providers and calls each `provider.aclose()` — mirrors [`LLMManager.aclose()`](../../lib/ai/manager.py) (`:261-269`).

---

## 4. Decisions (all user-confirmed 2026-07-27)

- **D1 — Scope: Video + Voice + Audio unified.** Same STT pipeline handles VIDEO, VIDEO_NOTE, VOICE, AUDIO. Voice messages are the highest-value case in practice (users send them constantly; bot is blind to them today). Same plumbing, one chat setting, one provider. ~Same effort as video-only because the pipeline is shared.
- **D2 — Trigger: Chat-setting auto, mirroring `PARSE_ATTACHMENTS`.** New `TRANSCRIBE_MEDIA` chat setting (BOOL, page=FRIEND, default=false). Runs in `_processMediaV2` message preprocessor. No always-on path; no slash command; no LLM tool. User wanted "done just like image parsing".
- **D3 — Audio extraction: PyAV.** Python wheel bundling ffmpeg libs — no system install, deterministic, async-friendly via `asyncio.to_thread`. Rejected: system ffmpeg (host dep), Docker sandbox (overkill).
- **D4 — Delivery: Reuse the `description` column.** Transcript lands in `media_attachments.description`, auto-injecting into the LLM message via the existing `updateMediaContent` → `formatForLLM` path. **Zero schema migration.** Mirrors how image descriptions work today. Rejected: new column, new table, structured JSON store.
- **D5 — Abstraction: Build `lib/stt/` provider registry now.** `AbstractSTTProvider` + `STTManager` + `YandexSpeechKitProvider`. ~150 extra lines over hardcoding, but swapping to Whisper/local/Azure later is a new provider file, not a rewrite. Matches repo conventions exactly.
- **D6 — HTTP transport: Raw httpx for the Yandex provider.** NOT `yandex-cloud-ml-sdk` STT surface — research flagged it as underdocumented (§9 R1). Raw httpx matches the proven [`lib/yandex_search/client.py`](../../lib/yandex_search/client.py) pattern (Api-Key header, `ProxyConfig.fromServiceConfig`, never-raise). The provider abstraction makes this swappable — `SdkYandexSpeechKitProvider` can be added later.
- **D7 — Timestamp granularity: Utterance-level in `description`.** Format `[HH:MM:SS] text` per line. Word-level data kept in `TranscriptionResult.raw` in-memory only (not persisted). LLM doesn't need word timestamps; utterance-level is human+LLM readable. Structured persistence is a v1.5 follow-up if retrieval/search use cases emerge.
- **D8 — Inline-only v1 (≤60 MB).** Object Storage (>60 MB, ≤1 GB) deferred — adds S3-compatible bucket infra, signed URLs, lifecycle management. v1 returns a clean error for files over the inline cap.

---

## 5. Alternatives considered

| Decision | Chosen | Rejected alternative | Why |
|---|---|---|---|
| Provider abstraction (D5) | `lib/stt/` registry now | Hardcode Yandex client | User explicitly chose abstraction; matches repo conventions; ~150 extra lines, fully reversible. |
| HTTP transport (D6) | Raw `httpx` | `yandex-cloud-ml-sdk` STT | SDK STT surface underdocumented (research flag); raw httpx matches `lib/yandex_search/`; provider abstraction makes it swappable later. |
| Audio extraction (D3) | PyAV | System ffmpeg / Docker sandbox | PyAV bundles ffmpeg libs in wheel — no host install, deterministic, async-friendly. Sandbox is overkill. |
| Transcript storage (D4) | Reuse `description` column | New `transcription` column / new table | Zero schema migration. Auto-inject path already wired. Matches user instruction "save as attachment's data". |
| Timestamp granularity (D7) | Utterance-level in `description` | Word-level in `description` | LLM doesn't need word timestamps; utterance-level `[HH:MM:SS]` is human+LLM readable. Structured data available in-memory if we later add a column. |
| Trigger (D2) | Separate `TRANSCRIBE_MEDIA` chat setting | Extend `PARSE_ATTACHMENTS` | User explicitly wanted a separate setting (friend tier, default off). Different cost profile from image parsing. |
| Trigger (D2) | Chat-setting auto | Always-on / slash-command / LLM-tool | User explicitly chose "done just like image parsing". Always-on too costly; slash-command too implicit; LLM-tool adds round-trip cost. |
| Sync vs async STT | Async `recognizeFileAsync` | Sync / streaming | Only async gives timestamps + the higher size limit. |

---

## 6. Trade-offs

- **Latency**: SpeechKit async adds 3-30s+ depending on audio length. The existing pipeline already awaits `PENDING` media (`ensured_message.py:1027`, `MAX_MEDIA_AWAIT_SECS`) — but for long videos this may exceed it. See §9 R2.
- **Cost**: Billed per second of audio. Guardrails (`max-duration-sec`, `max-file-size-mb`, per-chat rate limit) are mandatory. Default-off + friend-tier gating limits blast radius.
- **Inline-only v1 (≤60 MB)**: Object Storage support (>60 MB, ≤1 GB) deferred. Adds infra; worth it only if users actually send >60 MB files.
- **Single language v1** (`ru-RU`): Config-driven, but no auto-detection. SpeechKit supports auto-language; can enable later.
- **No structured persistence**: Word-level timestamps are not stored in v1; only the formatted text reaches the DB. Future analytics/search would need either a new column or a repurposed `metadata` JSON. Acceptable for v1 since the LLM use case doesn't need it.
- **PyAV wheel size**: ~30 MB. If venv size is a concern, fall back to system ffmpeg via `asyncio.create_subprocess_exec`.

---

## 7. Implementation plan (phased)

Ordered for low-risk, incremental verifiability. Each step ends with `make format lint && make test`. Tests live under `tests/` mirroring source per the AGENTS.md tests rule.

### Phase 1 — Foundation (no bot wiring yet)

| Step | Work | Specialist | Verify |
|---|---|---|---|
| 1 | Add `av==<pin>` to [`requirements.direct.txt`](../../requirements.direct.txt) under `# Runtime`, regenerate `requirements.txt` via `freeze-requirements`, `make install`. | software-developer | `./venv/bin/python3 -c "import av; print(av.__version__)"` (run as a script file, not `-c`). |
| 2 | Build `lib/stt/audio.py` (`extractAudio` + `_extractAudioSync` + `_AV_AVAILABLE` guard). Add `tests/lib/stt/test_audio.py` with a small fixture video file (commit a ~50 KB test mp4 under `tests/lib/stt/fixtures/`). | software-developer | Unit test: extract audio from fixture → assert WAV header (`RIFF`/`WAVE`) + non-zero duration. |
| 3 | Build `lib/stt/models.py` (`TranscriptionResult`, `TranscriptionAlternative`, `TranscriptionWord`, `STTResultStatus`, `formatTranscriptForLLM`). | software-developer | Unit test: format a fake `TranscriptionResult` → expected `[HH:MM:SS]` string; verify edge cases (empty alternatives, ms overflow, multi-hour). |
| 4 | Build `lib/stt/abstract.py` (`AbstractSTTProvider`) + `lib/stt/providers/base.py` (`BaseSTTProvider` with shared `ProxyConfig` init). | software-developer | Imports clean; `make lint` green. |
| 5 | **Research first, then build** `lib/stt/providers/yandex_speechkit_provider.py`. Verify the exact v3 request/response field names against the live API (or current SDK source) before writing the mapping. Add golden-data tests under `tests/lib/stt/golden/` with mocked `httpx` responses. | software-developer (research step first) | Golden tests cover: success path, operation polling, auth-error, timeout, malformed-response, empty-alternatives. All return `TranscriptionResult` (never raise). |
| 6 | Build `lib/stt/manager.py` (`STTManager`) + `lib/stt/__init__.py` (public exports). Hardcoded `type → class` map: `{"yandex-speechkit": YandexSpeechKitProvider}`. `aclose()` iterates providers. | software-developer | `STTManager({"provider": "yandex-speechkit", ...})` instantiates; `aclose()` propagates. |

### Phase 2 — Bot wiring

| Step | Work | Specialist | Verify |
|---|---|---|---|
| 7 | Add `[stt]` config in [`configs/00-defaults/stt.toml`](../../configs/00-defaults/stt.toml) + `ConfigManager.getSTTConfig()` accessor in [`internal/config/manager.py`](../../internal/config/manager.py). | software-developer | `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults --config-dir configs/local` shows merged `[stt]` with `${YC_API_KEY}` substituted. |
| 8 | Build `internal/services/stt/service.py` (`STTService` singleton, `injectSTTManager`, `transcribe()` with rate-limit + size guard + `asyncio.Semaphore(4)` global concurrency guard). Reset `_instance = None` in [`tests/conftest.py`](../../tests/conftest.py). | software-developer | Unit tests: oversize file → ERROR result; rate-limit hit → ERROR result; globally disabled → ERROR result; happy path with mocked manager. |
| 9 | Wire `STTManager` + `STTService` in [`main.py`](../../main.py) (init + shutdown `aclose()`). | software-developer | `make test` green; `import main` check passes; shutdown logs `STTManager.aclose()`. |
| 10 | Add `TRANSCRIBE_MEDIA` chat setting — all four sites per [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md) skill (§3.9). | software-developer | `/settings transcribe-media` shows the FRIEND-tier entry; default `false` in `--print-config`; toggling via `/set transcribe-media true` works. |

### Phase 3 — Pipeline integration

| Step | Work | Specialist | Verify |
|---|---|---|---|
| 11 | Extend `_processMediaV2` (Edits A/B/C in §3.10) + add `_transcribeMedia` (§3.11) + `_isTranscribable` helper. | software-developer | Integration test: send a fixture voice message through the pipeline with `TRANSCRIBE_MEDIA=true`, assert `description` populated + `status=DONE`. Regression test: image-parsing path still works unchanged (`PARSE_ATTACHMENTS=true`, IMAGE type). Regression test: with `TRANSCRIBE_MEDIA=false`, voice/video still get `MediaStatus.NEW` (unchanged behaviour). |
| 12 | End-to-end manual test in a real chat (Telegram voice + short video). Confirm `<media-description>` appears in LLM context via debug log. | you + software-developer | Manual sign-off. |

### Phase 4 — Documentation & release

| Step | Work | Specialist | Verify |
|---|---|---|---|
| 13 | Load [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill; update every doc listed in §8. | docs-writer | `make check-docs` green. |
| 14 | Add [`CHANGELOG.md`](../../CHANGELOG.md) entry under `## [Unreleased]` → Added. | software-developer | Entry present, follows [`docs/llm/changelog.md`](../llm/changelog.md) format. |

### Phase 5 — Future (deliberately out of scope)

- Object Storage input (>60 MB files).
- Speaker diarization.
- Auto-language detection.
- Structured transcript persistence (per-word JSON in a new column or `metadata`).
- `/transcribe` slash command for explicit on-demand transcription with visible reply.
- `SdkYandexSpeechKitProvider` as an alternative to the raw-httpx provider.
- Word-level confidence (would require v2 of SpeechKit, losing word timestamps — trade-off not yet justified).

---

## 8. Documentation impact

Per the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) decision matrix:

| Doc | Change |
|---|---|
| [`docs/llm/architecture.md`](../llm/architecture.md) | New ADR-014 (STT subsystem): layering, async-polling flow, design decisions. |
| [`docs/llm/services.md`](../llm/services.md) | New `STTService` section (singleton, `transcribe()`, guardrails). |
| [`docs/llm/libraries.md`](../llm/libraries.md) | New `lib/stt/` section (abstraction, providers, audio extraction). |
| [`docs/llm/configuration.md`](../llm/configuration.md) | New `[stt]` section + `transcribe-media` chat setting entry. |
| [`docs/llm/handlers.md`](../llm/handlers.md) | Note that `_processMediaV2` now also transcribes audio/video when the chat setting is on. |
| [`docs/llm/index.md`](../llm/index.md) | Bump service count (now 6 singletons incl. STTService); add `lib/stt/` to library list. |
| [`docs/database-schema.md`](../database-schema.md) and [`docs/database-schema-llm.md`](../database-schema-llm.md) | **No schema change**, but add a note that `media_attachments.description` is now also populated for AUDIO/VOICE/VIDEO/VIDEO_NOTE. |
| [`AGENTS.md`](../../AGENTS.md) | Add `STTService` to the Architecture cheatsheet's service list. |
| [`CHANGELOG.md`](../../CHANGELOG.md) | Added: "Transcription of voice/audio/video messages via Yandex SpeechKit (opt-in, friend-tier)." |

---

## 9. Risks & open questions

- **R1 — SpeechKit v3 field-name uncertainty** (research flag). The plan assumes `recognize_file_async` + operation polling + `alternatives[].words[].startTime`/`endTime` as Google `Duration` strings. **Step 5 starts by verifying this against the live API** (or current `yandex-cloud-ml-sdk` source) before writing the provider. If names differ, only `yandex_speechkit_provider.py` changes — the abstraction holds. **Mitigation**: golden-data tests with realistic mocked responses; manual smoke test against the real API as part of Step 12.
- **R2 — `MAX_MEDIA_AWAIT_SECS` adequacy for long videos.** If transcription takes longer than the await window, the first LLM round won't see the transcript (it'll be `None`). Acceptable for v1 (transcript lands late; mentioning the audio again in a follow-up message picks it up), but worth measuring. **Mitigation**: measure typical SpeechKit latency in Step 12; if problematic, either increase `MAX_MEDIA_AWAIT_SECS` or move long transcriptions to a delayed-task model.
- **R3 — PyAV wheel size / install impact.** PyAV wheels are ~30 MB. Confirm acceptable in the venv. **Mitigation**: if problematic, fall back to system ffmpeg via `asyncio.create_subprocess_exec` — only `lib/stt/audio.py` changes.
- **R4 — Speaker diarization.** Out of scope for v1 — single-speaker assumption. SpeechKit v3 supports it; worth a follow-up if multi-speaker videos are common.
- **R5 — Object Storage for >60 MB files.** v1 returns a clean error for files over the inline limit. **Mitigation**: log the skip at INFO so operators can spot demand; v1.5 adds Object Storage if there's uptake.
- **R6 — Word-level confidence always 0 in v3** (research flag). If confidence scores become important, v2 of SpeechKit returns them — but v2 lacks word timestamps. Trade-off deferred.
- **R7 — Concurrent transcription storms.** If a chat dumps 20 voice messages at once, 20 SpeechKit operations fire simultaneously. **Mitigation**: per-chat rate limiter caps per-chat concurrency; `STTService._globalSema = asyncio.Semaphore(4)` caps global in-flight STT calls to protect the SpeechKit quota. Tunable via the semaphore size (hardcoded in v1; consider config in v1.5 if needed).
- **R8 — Captions on voice/video messages.** If the user sends a voice message with a caption, both should reach the LLM. Today the caption stays as `messageText` and the transcript lands in `mediaContent` — they're independent fields and `formatForLLM` includes both. **Verified**: no conflict; no special handling needed.
