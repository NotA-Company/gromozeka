# Speech -- Text-to-Speech and Speech-to-Text

Audio capabilities via the `sdk.speechkit` domain, powered by Yandex
SpeechKit.

## Text-to-Speech (TTS)

### Creating a TTS Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Full constructor form
tts = sdk.speechkit.text_to_speech(
    voice="oksana",
    audio_format="MP3",
    speed=1.0,
)

# Alias
tts = sdk.speechkit.tts(voice="oksana", audio_format="MP3")
```

### TTS Configuration (TextToSpeechConfig)

Configuration can be set at construction time or via `.configure()`:

```python
tts = sdk.speechkit.text_to_speech(voice="oksana", audio_format="MP3")

# Re-configure later
tts.configure(speed=1.5, volume=0.7)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `audio_format` | `AudioFormat` | UNDEFINED | Output format. `WAV`, `MP3`, `OGG_OPUS`, `PCM16(sample_rate, channels=1)` |
| `voice` | `str \| None` | UNDEFINED | Voice name, e.g., `"oksana"`, `"alice"`, `"ermil"` |
| `role` | `str \| None` | UNDEFINED | Voice role/character |
| `speed` | `float \| None` | UNDEFINED | Speech speed. Default 1.0 |
| `volume` | `float \| None` | UNDEFINED | Volume. MAX_PEAK: (0,1] default 0.7; LUFS: [-145, 0) default -19 |
| `pitch_shift` | `float \| None` | UNDEFINED | Pitch shift in Hz. Range [-1000, 1000], default 0 |
| `loudness_normalization` | `LoudnessNormalization \| None` | UNDEFINED | `MAX_PEAK` or `LUFS` |
| `model` | `str \| None` | UNDEFINED | TTS model name |
| `duration_ms` | `int \| None` | UNDEFINED | Target duration in ms |
| `duration_min_ms` | `int \| None` | UNDEFINED | Minimum duration in ms |
| `duration_max_ms` | `int \| None` | UNDEFINED | Maximum duration in ms |
| `single_chunk_mode` | `bool` | UNDEFINED | Return single audio chunk. Default `False` |

### Audio Formats

```python
from yandex_ai_studio_sdk._speechkit.enums import AudioFormat

# Simple formats
AudioFormat.MP3
AudioFormat.WAV
AudioFormat.OGG_OPUS

# PCM16 with parameters
AudioFormat.PCM16(sample_rate_hertz=16000, channels=1)
```

### Loudness Normalization

```python
from yandex_ai_studio_sdk._speechkit.enums import LoudnessNormalization

LoudnessNormalization.MAX_PEAK  # Peak normalization, volume range (0, 1]
LoudnessNormalization.LUFS     # LUFS normalization, volume range [-145, 0)
```

### Execution Methods

#### `run()` -- Complete Synthesis

```python
result: TextToSpeechResult = await tts.run("Hello, world!", timeout=60)
```

Synthesizes the full text and returns the complete audio.

#### `run_stream()` -- Streaming Synthesis

```python
async for chunk in await tts.run_stream("Hello, world!", timeout=60):
    # chunk: TextToSpeechResult
    audio_data = chunk.data
    text = chunk.text
    start_ms = chunk.start_ms
    length_ms = chunk.length_ms
```

Returns audio chunks as they are generated, enabling low-latency playback.

#### `create_bistream()` -- Bidirectional Streaming

```python
stream = tts.create_bistream(timeout=600)
# Send text chunks and receive audio chunks in real-time
```

Creates a bidirectional streaming connection for interactive TTS (e.g.,
conversational agents). Timeout default is 600s (10 minutes).

### TextToSpeechResult

```python
@dataclass(frozen=True)
class TextToSpeechResult:
    chunks: tuple[TextToSpeechChunk, ...]
```

| Property | Type | Description |
|---|---|---|
| `.data` | `bytes` | Joined audio data from all chunks |
| `.text` | `str` | Text that was synthesized |
| `.start_ms` | `int` | Start time in ms |
| `.length_ms` | `int` | Duration in ms |
| `.end_ms` | `int` | End time in ms |
| `.size_bytes` | `int` | Audio data size in bytes |
| `.audio_format` | `AudioFormat` | Output audio format |

### TextToSpeechChunk

| Field | Type | Description |
|---|---|---|
| `.data` | `bytes` | Audio data for this chunk |
| `.text` | `str` | Text segment for this chunk |
| `.start_ms` | `int` | Start time in ms |
| `.length_ms` | `int` | Duration in ms |

### Complete TTS Example

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Create TTS with MP3 output
tts = sdk.speechkit.tts(
    voice="oksana",
    audio_format="MP3",
    speed=1.0,
    loudness_normalization="LUFS",
)

# Generate full audio
result = await tts.run("Hello, world!", timeout=60)

# Save to file
with open("output.mp3", "wb") as f:
    f.write(result.data)

print(f"Generated {result.size_bytes} bytes, {result.length_ms}ms duration")

# Streaming synthesis
async for chunk in await tts.run_stream("A longer text that benefits from streaming"):
    # Write each chunk to a buffer or stream to a client
    audio_buffer.extend(chunk.data)
```

---

## Speech-to-Text (STT)

### Creating an STT Model

```python
# Full constructor form
stt = sdk.speechkit.speech_to_text(
    audio_format=AudioFormat.WAV,
    language_codes="auto",
)

# Alias
stt = sdk.speechkit.stt(
    audio_format=AudioFormat.WAV,
    language_codes="auto",
)
```

**Note**: `audio_format` is **required** for STT (no default).

### STT Configuration (SpeechToTextConfig)

| Parameter | Type | Default | Description |
|---|---|---|---|
| `audio_format` | `AudioFormat` | REQUIRED | Input audio format. `WAV`, `MP3`, `OGG_OPUS`, `PCM16(...)` |
| `model` | `str \| None` | UNDEFINED | STT model name |
| `language_codes` | `LanguageCodesInputType \| None` | UNDEFINED | Language code(s). `"auto"`, `"ru_RU"`, `"en_US"`, etc. |
| `text_normalization` | `TextNormalization \| bool \| None` | UNDEFINED | Text normalization rules |
| `eou_classifier` | `EndOfUtteranceClassifier \| bool \| None` | UNDEFINED | End-of-utterance detection |
| `recognition_classifiers` | `RecognitionClassifiersInputType \| bool \| None` | UNDEFINED | Additional recognition classifiers |
| `speech_analysis` | `SpeechAnalysis \| None` | UNDEFINED | Speech analysis configuration |
| `speaker_labeling` | `bool \| None` | UNDEFINED | Enable speaker diarization |
| `llm_post_process` | `LLMPostProcessing \| None` | UNDEFINED | LLM-based post-processing |

### Supported Languages

| Code | Language |
|---|---|
| `auto` | Auto-detect |
| `ru_RU` | Russian |
| `en_US` | English (US) |
| `de_DE` | German |
| `es_ES` | Spanish |
| `fi_FI` | Finnish |
| `fr_FR` | French |
| `he_IL` | Hebrew |
| `it_IT` | Italian |
| `kk_KZ` | Kazakh |
| `nl_NL` | Dutch |
| `pl_PL` | Polish |
| `pt_PT` | Portuguese (PT) |
| `pt_BR` | Portuguese (BR) |
| `sv_SE` | Swedish |
| `tr_TR` | Turkish |
| `uz_UZ` | Uzbek |

### Input Types

| Method | Input Type | Description |
|---|---|---|
| `run()` | `bytes \| Sequence[bytes \| int]` | Audio bytes; int values = silence in ms |
| `run_stream()` | `bytes \| Sequence[bytes \| int]` | Same as `run()` |
| `run_deferred()` | `str \| bytes` | S3 URL (str) or audio bytes |
| `create_bistream()` | N/A | Bidirectional streaming |

### Execution Methods

#### `run()` -- Real-Time Recognition

```python
result: SpeechToTextResult = await stt.run(audio_bytes, timeout=60)
# Or with silence markers:
result = await stt.run([audio_chunk_1, 500, audio_chunk_2], timeout=60)
# 500 = 500ms silence between chunks
```

Performs complete recognition on the provided audio.

#### `run_stream()` -- Streaming Recognition

```python
async for event in await stt.run_stream(audio_bytes, timeout=60):
    # event: SpeechToTextStreamingEvent
    if event.final:
        print(f"Final: {event.alternatives[0].text}")
    else:
        print(f"Partial: {event.alternatives[0].text}")
```

Returns a stream of recognition events with partial and final results.

#### `run_deferred()` -- Asynchronous File Recognition

```python
# From audio bytes
operation = await stt.run_deferred(audio_bytes, timeout=60)

# From S3 URL
operation = await stt.run_deferred("s3://bucket/path/to/audio.wav", timeout=60)

# Wait for result
result = await operation
```

For long audio files. Returns `AsyncOperation[DeferredSpeechToTextResult]`.

#### `attach_deferred()` -- Attach to Existing Operation

```python
operation = stt.attach_deferred(operation_id="...", timeout=60)
result = await operation
```

#### `create_bistream()` -- Bidirectional Streaming

```python
stream = stt.create_bistream(timeout=600)
# Send audio chunks and receive recognition results in real-time
```

For interactive/real-time speech recognition (e.g., voice assistants). Timeout
default is 600s (10 minutes).

#### `get_recognition_result()` -- Get Deferred Result

```python
result = await stt.get_recognition_result(operation_id="...", timeout=60)
```

Retrieve the result of a deferred recognition operation by ID.

### SpeechToTextResult

The result contains utterances with full recognition details:

```python
@dataclass(frozen=True)
class Utterance:
    events: tuple[SpeechToTextStreamingEvent, ...]
    classifiers: dict[str, ClassifierResult]
    speaker_analysis: SpeakerAnalysis | None
    timespan: TimeSpan
    finals: tuple[Alternatives, ...]
    final_refinements: tuple[FinalRefinement, ...]
    final_classifiers: tuple[FinalClassifierResult, ...]

    # Properties:
    # .final_text: str  -- the final recognized text
    # .final_refinement_text: str
    # .text: str  -- same as final_text
```

### SpeechToTextStreamingEvent

Individual events in the streaming recognition output:

| Field | Type | Description |
|---|---|---|
| `event_type` | str | Type of recognition event |
| `alternatives` | tuple | Recognition alternatives |
| `final` | bool | Whether this is a final (stable) result |
| `final_refinement` | ... | Refined final result |
| `classifiers` | ... | Classification results |

### Complete STT Example

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth
from yandex_ai_studio_sdk._speechkit.enums import AudioFormat

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Create STT model
stt = sdk.speechkit.stt(
    audio_format=AudioFormat.WAV,
    language_codes="auto",
    speaker_labeling=True,
)

# Read audio file
with open("recording.wav", "rb") as f:
    audio_bytes = f.read()

# Real-time recognition
result = await stt.run(audio_bytes, timeout=60)
for utterance in result:
    print(f"Recognized: {utterance.text}")

# Streaming recognition
async for event in await stt.run_stream(audio_bytes, timeout=60):
    if event.final:
        print(f"Final: {event.alternatives[0].text}")

# Deferred recognition (for long audio)
operation = await stt.run_deferred(audio_bytes, timeout=60)
deferred_result = await operation
```

### Method Availability

| Method | Available | Timeout (default) | Input Type |
|---|---|---|---|
| `run()` | Yes | 60s | `bytes \| Sequence[bytes \| int]` |
| `run_stream()` | Yes | 60s | `bytes \| Sequence[bytes \| int]` |
| `run_deferred()` | Yes | 60s | `str (S3 URL) \| bytes` |
| `attach_deferred()` | Yes | 60s | `str (operation_id)` |
| `get_recognition_result()` | Yes | 60s | `str (operation_id)` |
| `create_bistream()` | Yes | 600s | N/A |
