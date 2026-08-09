# Golden Data Tests — Yandex SpeechKit STT Provider

This directory contains an [aurumentation](../../../../lib/aurumentation)-powered
golden record/replay test suite for
[`YandexSpeechKitProvider`](../../../../lib/stt/providers/yandex_speechkit.py).
It records real Yandex SpeechKit v3 responses once (manually, with credentials)
and replays them through the real provider + parser in CI (offline,
deterministic) on every `make test`.

This resolves the STT feature's **release gate-1**: the committed recordings
verify the live `getRecognition` streaming-JSON framing with its top-level
`result` wrapper (see `docs/design/lib-stt-v1.md` §7.3 / §13.3). Bare-envelope
parsing remains defensive compatibility, not a release blocker.

## How it works

```
         RECORD (manual, once)                    REPLAY (CI, every make test)
         ─────────────────────                    ─────────────────────────────

  input/sample.ogg                           data/*.json
  (any supported clip)                       (committed — the ONLY thing CI needs)
        │                                              │
        ▼                                              ▼
  YandexSTTScenarioRunner.run()           loadGoldenData()
   reads clip → runBytes(data)              │
        │                                   │ recover audio bytes from the
        ▼                                   │ fixture's recognizeFileAsync POST
  YandexSpeechKitProvider                   │ body (content field, base64 → bytes)
        │                                   ▼
   httpx ──► real Yandex API             YandexSTTScenarioRunner.runBytes(data)
        │                                        │
   RecordingTransport                            ▼
        │                                   YandexSpeechKitProvider
        ▼                                        │
  data/*.json ◄───────────────────────  httpx ──► ReplayTransport
  (masked HTTP traffic;                        (matches URL + body)
   audio embedded as base64)
```

**Key design point: replay is self-contained.** The audio clips under `input/`
are committed TTS-generated synthetic samples, and so are the `data/*.json`
fixtures. Replay never reads the clip on disk: it RECOVERS the submitted audio
bytes from the committed fixture itself — the recorded `recognizeFileAsync`
POST body carries `content` = `base64(audio.data)`, which is NOT secret-masked
(base64 cannot contain the literal API-key substring). The replay test
`base64.b64decode`s that field and feeds the bytes to `runBytes()` — it never
touches `input/*.ogg`.

The [`YandexSTTScenarioRunner`](scenario_runner.py) is the **impedance adapter**:
aurumentation's `collectGoldenData` can only pass JSON-serialisable kwargs
(strings/dicts/lists), but `provider.stt()` takes raw `bytes`. The runner's
`__init__` builds the provider from credential kwargs; its `run()` method (the
record entry) takes an `audioPath` string, reads the bytes from disk, and
delegates to `runBytes(data)`; `runBytes(data)` (the replay entry) takes bytes
directly. This mirrors
[`DivinationScenarioRunner`](../../divination/golden/scenario_runner.py).

## Files

| File | Purpose |
|------|---------|
| `scenario_runner.py` | Impedance adapter: builds the provider; `run()` reads audio bytes from disk (record), `runBytes()` takes bytes directly (replay). |
| `collect.py` | Manual recording driver. Run with credentials to produce `data/*.json`. Emits a loud privacy warning (audio is embedded in fixtures). |
| `input/scenarios.json` | Scenario definitions (credentials as `${VAR}` placeholders, audio paths). |
| `input/*.ogg` | Audio clips — committed TTS-generated synthetic samples for self-contained CI replay. Only needed for RECORDING; replay recovers bytes from the fixture. |
| `data/*.json` | Recorded fixtures (masked HTTP traffic + metadata + embedded audio as base64). The ONLY thing CI needs. |
| `test_golden.py` | Replay tests: sanity checks + parametrised replayer over `data/`. Recovers audio bytes from the fixture (never reads `input/*.ogg`). |

## Manual recording workflow

### 1. Set credentials

```bash
export YANDEX_API_KEY=<your Api-Key>
export YANDEX_FOLDER_ID=<your folder ID>
# or put them in a .env file at the repo root
```

### 2. Provide audio clips

Drop **short** (< 30 s) voice clips into `input/`:

```
input/sample_ru.ogg   # Russian speech (scenario: yandex_basic_transcription_ru)
input/sample_en.ogg   # English speech (scenario: yandex_english_transcription_en)
```

Any supported container is fine (OGG_OPUS, MP3, WAV, or even a transcode-
triggering one like M4A — the fixture captures the post-extraction bytes either
way; replay is format-agnostic). The clips are committed TTS-generated synthetic
samples. **Use throwaway/synthetic clips only**: the audio content is embedded
(base64) in the committed fixtures, so whatever voice data you record lives in
the repo. The collector prints a loud privacy warning after recording to remind
you of this.

### 3. Record

```bash
./venv/bin/python3 tests/lib/stt/golden/collect.py
```

This drives `collectGoldenData` over every scenario in `input/scenarios.json`,
hits the real Yandex SpeechKit API, and writes masked fixtures to `data/`.

### 4. Verify no secrets leaked

```bash
grep -r "$YANDEX_API_KEY" tests/lib/stt/golden/data/
grep -r "$YANDEX_FOLDER_ID" tests/lib/stt/golden/data/
```

Both should return nothing. The `SecretMasker` masks credentials in recorded
headers/bodies, but **always double-check** before committing.

### 5. Run the replay tests

```bash
./venv/bin/pytest tests/lib/stt/golden/test_golden.py -v
```

All replayer tests should pass with `FINAL`, at least one segment, generic attribution-tag set
`{0, 1}`, and result role `SPEAKER`. The committed fixtures are known-speech mono
recordings submitted with speaker labeling enabled, so `NO_SPEECH` would indicate
that a final was lost.

## Gate-1 resolution

The committed fixtures record the verified wrapped `getRecognition` form
(`{"result": {...}}`). `_resolveEnvelope` also accepts a bare form (`{...}`) as
defensive compatibility for variant or future input. When recording a future
fixture, inspect its response body and compare its framing to
[`lib/stt/providers/yandex_events.py`](../../../../lib/stt/providers/yandex_events.py).
If the live framing changes:

1. Adjust `_resolveEnvelope` (or the event-field readers) to match the real shape.
2. Update the unit-test fixtures in
   [`tests/lib/stt/providers/test_yandex_events.py`](../providers/test_yandex_events.py)
   to reflect the confirmed framing.
3. Re-run the golden replayer tests to confirm the real response still parses.

## Format-agnostic replay

Recording can use **any supported clip** (OGG_OPUS, MP3, WAV, or even a
transcode-triggering container like M4A). There is no OGG_OPUS-only
requirement. Here's why:

- Replay feeds the **post-extraction** bytes (what was actually submitted to
  Yandex), NOT the source clip bytes. These are recovered from the committed
  fixture's recorded `recognizeFileAsync` POST body (`content` field,
  base64-decoded).
- `extractAudio()` re-probes those bytes: since they are already a supported
  container (whatever the provider submitted), it passes them through verbatim —
  `data` = input bytes.
- The re-submitted POST body (`base64(data)`) is therefore byte-identical to the
  recording → `ReplayTransport` body match succeeds.

This sidesteps transcode non-determinism entirely: even if the original clip
triggered a transcode (e.g. WAV → OGG_OPUS via PyAV/libopus, which can vary
across runs), the fixture captures the post-transcode bytes — and replay just
re-sends those exact bytes. The source clip format is irrelevant to replay.

The only place format matters is recording time: you need a clip that
`extractAudio` can actually decode (any container PyAV/FFmpeg supports).

## How the tests skip when no fixtures exist

On a fresh checkout (no `data/*.json`):

- `testGoldenFixturesAreRecorded` → **SKIP** with recording instructions.
- `testReplayTranscription` → **0 parametrised cases** (empty fixture list),
  so pytest does not even collect them — the suite is green.
- `testScenariosFileIsValid` → **PASSES** (validates `scenarios.json` only).

So `make test` is always green, even before any human records fixtures.

## Why per-fixture parametrisation (not the merged-meta-scenario helper)

This suite parametrises the replayer **per fixture** (`testReplayTranscription`
gets one `fixturePath` per `data/*.json`), rather than using the shared
`baseGoldenDataProvider` + merged-meta-scenario helper that some other suites
use (see [`docs/llm/aurumentation.md`](../../../../docs/llm/aurumentation.md)
§6.1 / §8.3). The reason: each STT scenario is an **independent submit → poll →
fetch → delete lifecycle** with its own audio bytes. Merging all recordings into
one flat list would expose the suite to the `ReplayTransport` *first-match-wins*
gotcha (§8.3) — two recordings with near-identical request signatures would make
the second unreachable. Per-fixture isolation gives each scenario its own
recording list, so there is no cross-scenario collision.

## Assertion philosophy

The replayer requires `FINAL`, non-empty segments, the fixtures' generic attribution-tag
set `{"0", "1"}`, and result role `SPEAKER`. This catches malformed parsing, a dropped final,
or role/attribution conflation that could otherwise appear as
`NO_SPEECH`. Specific transcript text remains intentionally unasserted.
