"""Scenario runner for the STT golden-data collector (bytes/JSON impedance adapter).

This module bridges the impedance mismatch between aurumentation's JSON-driven
scenario format and the STT provider's bytes-oriented API:

:func:`lib.aurumentation.collector.collectGoldenData` instantiates a class from
``init_kwargs`` (env-substituted strings/dicts/lists) and calls a method with
``kwargs`` — all JSON-serialisable. But
:meth:`lib.stt.abstract.AbstractSTTProvider.stt` takes raw ``bytes`` (the source
audio), which JSON cannot carry. Raw bytes are not representable in a
``scenarios.json`` file, and :func:`lib.aurumentation.collector.substituteEnvVars`
handles only strings/dicts/lists — it cannot materialise a binary audio payload.

:class:`YandexSTTScenarioRunner` resolves this with TWO entry points:

- **Record entry** (:meth:`run`): receives an ``audioPath`` STRING (a path
  relative to this module, e.g. ``"input/sample.ogg"``), reads the raw bytes
  from disk, and delegates to :meth:`runBytes`. The collector drives this via
  the scenario's ``method``/``kwargs`` — it needs a real clip on disk because it
  genuinely hits the Yandex API.
- **Replay entry** (:meth:`runBytes`): receives the audio ``data`` directly as
  ``bytes``. The replay test (:mod:`tests.lib.stt.golden.test_golden.py`)
  recovers those bytes from the committed fixture itself (see *Self-contained
  replay* below) and calls this — it NEVER touches the ``input/*.ogg`` clip on
  disk.

Because the provider builds its ``httpx.AsyncClient`` in ``__init__``,
aurumentation's class-level patch (active inside the
``async with GoldenDataRecorder(...)`` / ``GoldenDataReplayer(...)`` context)
auto-intercepts it — no custom transport patcher is needed (unlike the AI suite,
which needs an OpenAI patcher).

**Self-contained replay (never touches the clip on disk).** The audio clips
under ``input/`` are committed TTS-generated synthetic samples, and the
``data/*.json`` fixtures are committed too. Replay RECOVERS the submitted audio
bytes from the committed fixture: the recorded ``recognizeFileAsync`` POST body
carries ``content`` = ``base64(ExtractedAudio.data)`` (the audio bytes are NOT
secret-masked — they are base64, which cannot contain the literal API-key
substring; see :class:`lib.aurumentation.masker.SecretMasker`). The replay test
``base64.b64decode``\\ s that field to obtain the exact bytes that were
submitted, then feeds them to :meth:`runBytes`.

**Format-agnostic recording.** Because replay feeds the *post-extraction* bytes
(what was actually submitted to Yandex), not the *source* clip bytes,
:func:`lib.stt.audio.extractAudio` always re-probes them as a supported
container and passes them through verbatim — so the re-submitted body is
byte-identical to the recording regardless of the original recording clip's
format. Recording can therefore use ANY supported clip (OGG_OPUS, MP3, WAV, or
even a transcode-triggering container like M4A — the fixture captures the
post-extraction bytes either way). There is no OGG_OPUS-only requirement.
"""

from __future__ import annotations

from pathlib import Path

from lib.stt.models import TranscriptionResult
from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

#: Directory containing this module. Audio clip paths in ``scenarios.json`` are
#: resolved relative to here so both ``collect.py`` (run from repo root) and
#: ``test_golden.py`` (run by pytest from repo root) find the same file
#: regardless of the current working directory.
_MODULE_DIR: Path = Path(__file__).resolve().parent


class YandexSTTScenarioRunner:
    """End-to-end scenario runner bridging aurumentation JSON scenarios to the STT bytes API.

    A single instance is constructed per scenario by
    :func:`lib.aurumentation.collector.collectGoldenData`, which forwards the
    scenario's ``init_kwargs`` into ``__init__`` and then awaits :meth:`run`
    with the scenario's ``kwargs``. The runner builds a
    :class:`YandexSpeechKitProvider` (whose ``httpx.AsyncClient`` is
    auto-intercepted by aurumentation's class-level patch) and delegates to
    ``provider.stt(data)`` — exercising the real extract + submit + poll +
    getRecognition + parse + delete lifecycle end to end.
    """

    def __init__(
        self,
        *,
        apiKey: str,
        folderId: str,
        model: str = "general",
        language: str = "ru-RU",
    ) -> None:
        """Build the YandexSpeechKitProvider from credential kwargs.

        Args:
            apiKey: Yandex Cloud API key. At collection time this arrives as
                ``${YANDEX_API_KEY}`` (resolved by ``substituteEnvVars``); at
                replay time it is a dummy non-empty string (the replay never
                sends real credentials — the recorded responses are matched by
                URL/body, not headers).
            folderId: Yandex Cloud folder ID. Same ``${YANDEX_FOLDER_ID}``
                substitution / dummy-replay semantics as ``apiKey``.
            model: Recognition model name (defaults to ``"general"``).
            language: BCP-47 language code for the WHITELIST restriction
                (defaults to ``"ru-RU"``; set to ``"en-US"`` etc. per scenario).

        Raises:
            ValueError: Propagated from :class:`YandexSpeechKitProvider`
                constructor validation (missing/empty credentials).
        """
        self._provider: YandexSpeechKitProvider = YandexSpeechKitProvider(
            apiKey=apiKey,
            folderId=folderId,
            model=model,
            language=language,
        )

    async def runBytes(self, *, data: bytes) -> TranscriptionResult:
        """Transcribe raw audio bytes through the full provider lifecycle (replay entry).

        Delegates to :meth:`AbstractSTTProvider.stt
        <lib.stt.abstract.AbstractSTTProvider.stt>` — the never-raise
        extract+transcribe entry point. The provider's httpx client is closed in
        a ``finally`` block so no resource warning leaks.

        This is the entry the replay test calls, feeding it bytes recovered from
        the committed fixture (see the module docstring's *Self-contained
        replay* section). The record entry (:meth:`run`) also delegates here
        after reading the clip from disk.

        Args:
            data: The source audio bytes to extract and transcribe. At record
                time these are read from ``input/*.ogg``; at replay time they are
                recovered from the fixture's recorded submit body.

        Returns:
            TranscriptionResult: FINAL / NO_SPEECH on success, or ERROR with an
            :class:`~lib.stt.models.STTErrorCode` on failure (the provider never
            raises for expected failures).
        """
        try:
            return await self._provider.stt(data)
        finally:
            # Closing the patched httpx client here is safe even DURING
            # recording: the RecordingTransport has already buffered every call
            # on its own in-memory list (independent of the client wrapper), and
            # the recorder's getRecordedRecordings() reads from that buffer
            # afterwards. During replay the ReplayTransport likewise holds the
            # recorded responses independently. aclose() only tears down the
            # client wrapper — it does not discard recorded data. Do not
            # "reorder" this before the stt() call hoping to "flush" recordings.
            await self._provider.aclose()

    async def run(self, *, audioPath: str) -> TranscriptionResult:
        """Read audio bytes from disk and transcribe (record entry).

        Resolves ``audioPath`` relative to this module's directory (so the same
        ``"input/sample.ogg"`` value works from any CWD), reads the raw bytes,
        and delegates to :meth:`runBytes`. This is the method the collector
        drives (via the scenario's ``method``/``kwargs``); it requires a real
        clip on disk because recording genuinely hits the Yandex API. The
        replay test does NOT call this — it recovers bytes from the fixture and
        calls :meth:`runBytes` directly (see the module docstring's
        *Self-contained replay* section).

        Args:
            audioPath: Path to the audio clip, relative to this module's
                directory (e.g. ``"input/sample.ogg"``). Any supported container
                is fine (OGG_OPUS, MP3, WAV) — replay is format-agnostic (see
                the module docstring).

        Returns:
            TranscriptionResult: FINAL / NO_SPEECH on success, or ERROR with an
            :class:`~lib.stt.models.STTErrorCode` on failure (the provider never
            raises for expected failures).

        Raises:
            FileNotFoundError: When the audio clip does not exist at the resolved
                path.
        """
        fullPath: Path = _MODULE_DIR / audioPath
        if not fullPath.exists():
            raise FileNotFoundError(f"Audio clip not found: {fullPath}")
        data: bytes = fullPath.read_bytes()
        return await self.runBytes(data=data)


__all__ = ["YandexSTTScenarioRunner"]
