---
category: reference
---

# `lib/aurumentation` — Golden Data Testing System v2 (Reference)

> **Audience:** maintainers of the library itself and of the golden-data suites.
> **Purpose:** the internals, public API, data flow, and gotchas of the HTTP
> record/replay test infrastructure.
> For the *user-facing* workflow (how to write a golden test, how to run the
> collector), see [`testing.md`](testing.md) §6 — this doc does not duplicate it.

---

## 1. What it is

`lib/aurumentation` is the repo's HTTP **record/replay** (VCR-style) test
infrastructure. The package docstring calls it *"Golden Data Testing System v2"*
([`lib/aurumentation/__init__.py`](../../lib/aurumentation/__init__.py):1).

The idea: capture a client's **real wire shape** (request URL, method, headers,
params, body + full response) once, against a live API, into JSON fixtures with
secrets masked out. Then, in CI, replay those fixtures with zero network access
— fast, deterministic, offline. Because replay intercepts at the `httpx`
transport layer, the client under test runs its **real code path** (real URL
construction, real header signing, real response parsing); only the network
hop is swapped for a recorded cassette. This is stricter than hand-fabricated
mocks, which can drift silently from what the client actually sends.

> **httpx2 alias note:** the repo runs on `httpx2` (Pydantic-org fork of
> `httpx 0.28.1`, API-identical), aliased as `httpx` process-wide via
> `httpx2.alias_httpx()` at the top of `main.py` and `tests/conftest.py`
> (see [`architecture.md`](architecture.md) ADR-021). Every `httpx.AsyncClient` /
> `httpx.AsyncHTTPTransport` reference below is literally what the source reads,
> and at runtime those are `httpx2.AsyncClient` / `httpx2.AsyncHTTPTransport`.
> The record/replay patching mechanism is unaffected by the alias — it patches
> the module-global `httpx.AsyncClient`, which the alias points at `httpx2`'s.

**Name vs. capability.** The package directory is `lib/aurumentation`; the
capability it provides is universally called **"golden data"** in the docs and
in fixture/test layout (`golden/` directories, `GOLDEN_DATA_PATH`, the
`Golden*` classes). Both names refer to the same thing.

**Etymology.** "aurumentation" derives from *aurum* — Latin for **gold** — a
play on the library's "golden data" purpose (recording and replaying "golden"
HTTP fixtures). It is **not** derived from "argumentation"; the superficial
resemblance is a common misreading.

**When to use it.** Use it for a client that talks to a slow, rate-limited,
costly, or auth-gated HTTP API where you want regression coverage of the
client's request construction and response parsing. **When not to:** pure-logic
code with no I/O (just unit-test it), or code that does not route through
`httpx.AsyncClient` (e.g. the YC gRPC SDK — see the OpenAI-patcher gotcha
below).

---

## 2. Architecture — the nine modules

All paths under [`lib/aurumentation/`](../../lib/aurumentation/):

| Module | Role | Key symbols |
|---|---|---|
| [`__init__.py`](../../lib/aurumentation/__init__.py) | Public re-exports (a curated subset — see §3). | `collectGoldenData`, `GoldenDataRecorder`, `GoldenDataReplayer`, `GoldenDataProvider`, … |
| [`types.py`](../../lib/aurumentation/types.py) | `TypedDict` data models for fixtures, scenarios, and recorded HTTP calls. | `ScenarioDict`, `MetadataDict`, `HttpCallDict`, `HttpRequestDict`/`HttpResponseDict`, `GoldenDataScenarioDict` |
| [`transports.py`](../../lib/aurumentation/transports.py) | The two `httpx.AsyncHTTPTransport` subclasses that do the actual intercepting. | `RecordingTransport`, `ReplayTransport` |
| [`masker.py`](../../lib/aurumentation/masker.py) | Secret scrubbing for recorded traffic. | `SecretMasker` |
| [`recorder.py`](../../lib/aurumentation/recorder.py) | Recording coordinator: async ctx-mgr that globally patches `httpx.AsyncClient`, collects recordings, builds scenarios, writes files. | `GoldenDataRecorder` |
| [`replayer.py`](../../lib/aurumentation/replayer.py) | Replay coordinator: async ctx-mgr that globally patches `httpx.AsyncClient`, plus an explicit `createClient()`. | `GoldenDataReplayer` |
| [`provider.py`](../../lib/aurumentation/provider.py) | Loads JSON fixtures from disk, indexes them by name, builds replaying clients. | `GoldenDataProvider`, `loadGoldenData`, `findGoldenDataFiles` |
| [`collector.py`](../../lib/aurumentation/collector.py) | One-time "go record everything" driver: reads scenarios JSON, imports+runs each class/method, saves fixtures. Also exposes `substituteEnvVars` / `sanitizeFilename`. | `collectGoldenData`, `substituteEnvVars`, `sanitizeFilename` |
| [`cli.py`](../../lib/aurumentation/cli.py) | Alternate CLI entry point. **Not what consumers use** — see §6 / §8. | `main`, `importFunction`, `parseSecrets` |

The dependency graph is linear and one-directional:

```
collector ─▶ recorder ─▶ transports ─▶ types
provider  ─▶ replayer ─▶ transports ─▶ types
                       masker ─▶ types
```

`transports` and `masker` are leaves; `recorder`/`replayer` compose them;
`collector` and `provider` are the top-level orchestrators.

---

## 3. Public API

### 3.1 What `__init__.py` re-exports

[`__init__.py`](../../lib/aurumentation/__init__.py):8-20 re-exports a **curated
subset**:

- `collectGoldenData`, `sanitizeFilename` (from `collector`)
- `GoldenDataProvider`, `findGoldenDataFiles`, `loadGoldenData` (from `provider`)
- `GoldenDataRecorder`, `GoldenDataReplayer`
- The data model TypedDicts: `CollectorInputDict`, `GoldenDataScenarioDict`,
  `HttpCallDict`, `HttpRequestDict`, `HttpResponseDict`, `ScenarioDict`,
  `ScenarioInitKwargs`

**Notably NOT re-exported** (import these from their submodules):

- `SecretMasker` → `lib.aurumentation.masker`
- `RecordingTransport`, `ReplayTransport` → `lib.aurumentation.transports`
- `substituteEnvVars` → `lib.aurumentation.collector`
- `MetadataDict`, `GoldenDataFormat`, `GoldenDataFileFormat` → `lib.aurumentation.types`
- The CLI (`cli.py`)

### 3.2 Key signatures (verified against source)

```python
# recorder.py:43 — recording coordinator
GoldenDataRecorder(
    secrets: Optional[List[str]] = None,
    aenterCallback: Optional[PatchingRecorderCallback] = None,
    aexitCallback: Optional[PatchingRecorderCallback] = None,
)
# async ctx-mgr. Methods:
#   getRecordedRecordings() -> List[HttpCallDict]      # recorder.py:125 — masks + strips compression headers
#   clearRecordedCalls() -> None                        # recorder.py:156
#   createScenario(*, description, scenarioName=None, module, className, method,
#                  kwargs, initKwargs=None, recordings=None) -> GoldenDataScenarioDict   # recorder.py:162
#   saveGoldenData(filepath: str, metadata: MetadataDict) -> None   # recorder.py:218

# replayer.py:46 — replay coordinator
GoldenDataReplayer(
    scenario: GoldenDataScenarioDict,
    aenterCallback: Optional[PatchingReplayerCallback] = None,
    aexitCallback: Optional[PatchingReplayerCallback] = None,
)
# async ctx-mgr. Methods:
#   createClient() -> httpx.AsyncClient     # replayer.py:125 — explicit pre-wired client (no global patch)
#   verifyAllCallsUsed() -> bool            # replayer.py:137 — STUB, see §8

# provider.py:35 — fixture loader / query layer
GoldenDataProvider(goldenDataDirs: str | Sequence[str])
# sync + async ctx-mgr (no-ops). Methods:
#   loadAllScenarios() -> Dict[str, GoldenDataScenarioDict]   # provider.py:89
#   loadScenario(filename: str, basePath: Path) -> GoldenDataScenarioDict   # provider.py:53
#   getScenario(name: Optional[str]) -> GoldenDataScenarioDict   # provider.py:114 — None ⇒ merged "meta" scenario
#   createClient(scenarioName: Optional[str]) -> httpx.AsyncClient   # provider.py:139

# collector.py:89 — one-time record driver
collectGoldenData(
    scenarios: List[ScenarioDict],
    outputDir: Path,
    secrets: List[str],
    aenterCallback: Optional[PatchingRecorderCallback] = None,
    aexitCallback: Optional[PatchingRecorderCallback] = None,
) -> None

# Module-level helpers
loadGoldenData(filepath: str) -> GoldenDataScenarioDict            # provider.py:197
findGoldenDataFiles(directory: str) -> List[str]                   # provider.py:265  (rglob "*.json")
substituteEnvVars(value: Any, loadDotenv: bool = True) -> Any      # collector.py:23
sanitizeFilename(text: str) -> str                                 # collector.py:69

# transports.py
RecordingTransport(wrapped: Optional[httpx.AsyncHTTPTransport] = None, *args, **kwargs)   # transports.py:28
ReplayTransport(recordings: List[HttpCallDict], *args, **kwargs)                          # transports.py:99

# masker.py
SecretMasker(secrets: List[str], patterns: Optional[List[str]] = None)   # masker.py:41
```

The `PatchingRecorderCallback` / `PatchingReplayerCallback` aliases
([`recorder.py`](../../lib/aurumentation/recorder.py):21, [`replayer.py`](../../lib/aurumentation/replayer.py):16)
are `Callable[[Recorder], None] | Callable[[Recorder], Awaitable[None]]` — i.e.
a callback may be sync **or** async; the coordinator detects which via
`inspect.iscoroutinefunction` ([`recorder.py`](../../lib/aurumentation/recorder.py):92,
[`replayer.py`](../../lib/aurumentation/replayer.py):91). This is the extension
point the AI suite uses to also patch the OpenAI SDK (§6.2).

---

## 4. Record → replay data flow

### 4.1 How a recording is made (record path)

Driven by `collectGoldenData` ([`collector.py`](../../lib/aurumentation/collector.py):89):

1. **Load scenarios.** Each entry is a `ScenarioDict`
   ([`types.py`](../../lib/aurumentation/types.py):48): `module`, `class`,
   `method`, `init_kwargs`, `kwargs`, plus `name`/`description`.
2. **Resolve secrets.** Each name in `secrets` is first treated as an
   **environment-variable name** (`os.getenv(secret)`); only if that lookup
   fails is the literal string used ([`collector.py`](../../lib/aurumentation/collector.py):125-131).
3. **Substitute env vars** in `init_kwargs` and `kwargs` via `substituteEnvVars`
   ([`collector.py`](../../lib/aurumentation/collector.py):134-135). This
   handles `${VAR}` strings, recurses into dicts/lists, and even instantiates a
   nested `module`/`class` definition ([`collector.py`](../../lib/aurumentation/collector.py):46-60).
4. **Enter the recorder ctx-mgr** ([`recorder.py`](../../lib/aurumentation/recorder.py):64).
   `__aenter__` builds a `RecordingTransport` wrapping a real default
   `httpx.AsyncHTTPTransport`, then **reassigns the module-global**
   `httpx.AsyncClient` to a `PatchedAsyncClient` subclass that forces
   `kwargs["transport"] = recorder.transport` into every constructor
   ([`recorder.py`](../../lib/aurumentation/recorder.py):79-89). The original
   class is stashed for restore on exit. The optional `aenterCallback` runs here.
5. **Instantiate and call.** `module = importlib.import_module(modulePath)`;
   `instance = cls(**substitutedInitKwargs)`; `result = await method(**substitutedKwargs)`
   (sync method supported too — [`collector.py`](../../lib/aurumentation/collector.py):145-154).
   Because `httpx.AsyncClient` is globally patched, **any** client the
   instance constructs internally is auto-intercepted.
6. **`RecordingTransport.handle_async_request`** ([`transports.py`](../../lib/aurumentation/transports.py):40)
   captures `method`, `str(url)`, headers, `params` (from `url.params`), and
   the decoded request body; calls the **wrapped real transport**; reads the
   response (`aread()` if not already buffered); captures status, headers,
   decoded content; appends an `HttpCallDict` with an ISO-8601 UTC timestamp.
7. **Mask + save.** `saveGoldenData` calls `getRecordedRecordings()`
   ([`recorder.py`](../../lib/aurumentation/recorder.py):125), which runs every
   recording through `SecretMasker.maskHttpCall` and **strips `content-encoding`
   and `content-length`** from response headers (the stored content is already
   decompressed; keeping them would make replay double-decompress —
   [`recorder.py`](../../lib/aurumentation/recorder.py):143-150). It writes
   `{"metadata": …, "recordings": […]}` as indented UTF-8 JSON
   ([`recorder.py`](../../lib/aurumentation/recorder.py):218-239).
8. **Restore.** `__aexit__` runs the optional `aexitCallback`, then puts the
   original `httpx.AsyncClient` back ([`recorder.py`](../../lib/aurumentation/recorder.py):100-123).

The recorded `metadata` is built by the collector and contains
`name, description, module, class, method, init_kwargs` (**original, with
`${VAR}` placeholders preserved**), `kwargs`, and `result_type` (just
`type(result).__name__` — the actual return value is **discarded**;
[`collector.py`](../../lib/aurumentation/collector.py):166-176). `createdAt` is
**not** written by this path; the loader backfills it on read
([`provider.py`](../../lib/aurumentation/provider.py):256).

### 4.2 How replay intercepts (replay path)

Two equivalent entry styles, both ultimately constructing a `ReplayTransport`:

- **Global-patch ctx-mgr** (used by the consumer `test_golden.py` files):
  `async with GoldenDataReplayer(scenario):` reassigns `httpx.AsyncClient` to a
  patched subclass exactly as the recorder does
  ([`replayer.py`](../../lib/aurumentation/replayer.py):66-96). Any client built
  inside the block is auto-wired to the `ReplayTransport`. Construct your real
  client **after** entering the context.
- **Explicit client** (used by `GoldenDataProvider.createClient`):
  `replayer.createClient()` builds a fresh `ReplayTransport` + `httpx.AsyncClient`
  and returns it ([`replayer.py`](../../lib/aurumentation/replayer.py):125-135).
  No global patch — the caller owns the client.

`ReplayTransport.handle_async_request` ([`transports.py`](../../lib/aurumentation/transports.py):187)
normalises the incoming request (method, `str(url)`, `url.params`, decoded body)
and **linear-scans** `self.recordings`, returning the **first** entry whose
method, URL, params, and body all match. If none match it raises
`ValueError` ([`transports.py`](../../lib/aurumentation/transports.py):223).
Matching is **exact** except where the recorded value contains the
`***MASKED***` placeholder, in which case URL and body are treated as regexes
(`[^&]*` for the placeholder); params get a wildcard **only** for the
hardcoded `appid` key (other masked params are NOT wildcarded — see §8.2)
([`transports.py`](../../lib/aurumentation/transports.py):111-185). See §8 for
the masking/matching caveats.

Loading: `GoldenDataProvider.loadAllScenarios()` `rglob`s every `*.json` under
the configured dir(s) ([`provider.py`](../../lib/aurumentation/provider.py):101-112),
`loadGoldenData` parses each into a `GoldenDataScenarioDict`
([`provider.py`](../../lib/aurumentation/provider.py):197-262), and `getScenario(None)`
returns a **merged "meta" scenario** whose `recordings` list is the concatenation
of every loaded file's recordings ([`provider.py`](../../lib/aurumentation/provider.py):82-87).
That meta scenario is what most replay tests use when they don't care which
individual fixture served a given call.

---

## 5. On-disk fixture format

Each `data/*.json` file is a `GoldenDataFileFormat`
([`types.py`](../../lib/aurumentation/types.py):161):

```jsonc
{
  "metadata": {
    "name": "English query",
    "description": "Simple query in English",
    "module": "lib.yandex_search.client",
    "class": "YandexSearchClient",
    "method": "search",
    "init_kwargs": { "apiKey": "${YANDEX_SEARCH_API_KEY}", ... },  // placeholders preserved
    "kwargs":      { "queryText": "python programming" },
    "result_type": "dict"                                          // type(result).__name__ only
    // "createdAt" is absent on freshly-recorded files; loader backfills it
  },
  "recordings": [
    {
      "request":  { "method": "POST", "url": "...", "headers": {...},
                    "params": {...}, "body": "..." },
      "response": { "status_code": 200, "headers": {...}, "content": "..." },
      "timestamp": "2026-07-01T12:00:00+00:00"
    }
  ]
}
```

Secrets appear as `***MASKED***` everywhere they were matched (see §8.1).

---

## 6. The consumer pattern

### 6.1 Canonical directory shape

Every golden suite lives at `tests/lib/<service>/golden/` and contains:

| File | Purpose |
|---|---|
| `__init__.py` | Exports `GOLDEN_DATA_PATH` (the `data/` dir as a repo-root-relative string). Example: [`tests/lib/yandex_search/golden/__init__.py`](../../tests/lib/yandex_search/golden/__init__.py). |
| `input/scenarios.json` | The `List[ScenarioDict]` consumed by the collector. Example: [`tests/lib/yandex_search/golden/input/scenarios.json`](../../tests/lib/yandex_search/golden/input/scenarios.json). |
| `collect.py` | Run **locally** with real credentials to (re)record fixtures into `data/`. Never run in CI. |
| `test_golden.py` | The pytest module; loads `data/`, replays, asserts. Uses `findGoldenDataFiles` so an empty `data/` yields **zero** parametrised cases and stays green. |
| `data/*.json` | The recorded fixtures (committed; the whole point). |

The six existing suites:

| Suite | Layout notes |
|---|---|
| [`tests/lib/yandex_search/golden/`](../../tests/lib/yandex_search/golden/) | Simplest reference: one client, `search()` method, four query scenarios. |
| [`tests/lib/openweathermap/golden/`](../../tests/lib/openweathermap/golden/) | Weather client; multiple cities. |
| [`tests/lib/geocode_maps/golden/`](../../tests/lib/geocode_maps/golden/) | Geocoding; forward + reverse lookups. |
| [`tests/lib/ai/golden/`](../../tests/lib/ai/golden/) | LLM providers — needs the SDK patcher (§6.3). |
| [`tests/lib/divination/golden/`](../../tests/lib/divination/golden/) | Non-JSON inputs + extra assertions — needs a scenario runner (§6.4). |
| [`tests/lib/stt/golden/`](../../tests/lib/stt/golden/) | Binary (audio) input — recovers bytes from the fixture (per-fixture parametrisation; see §6.2 notes below). |

### 6.2 Three `collect.py` styles

There has been drift in how the per-service `collect.py` drives recording. The
accurate breakdown across the six suites:

- **Inline "copy-paste the loop" style** (openweathermap, yandex_search): the
  script **re-implements** the record loop inline, importing `sanitizeFilename`,
  `substituteEnvVars`, and `GoldenDataRecorder` directly and building the
  `metadata` dict by hand. See
  [`tests/lib/yandex_search/golden/collect.py`](../../tests/lib/yandex_search/golden/collect.py):29-97.
  These do **not** pass `aenterCallback`/`aexitCallback`, so they cannot patch
  anything beyond raw `httpx`.
- **Delegating WITHOUT callbacks** (geocode_maps, stt): the script imports
  `lib.aurumentation.collector as aurumentationCollector` and delegates to the
  real `aurumentationCollector.collectGoldenData(...)`, but passes **no**
  callbacks (its only local logic is setup around the delegate call — e.g.
  geocode_maps' rate-limiter setup or stt's env-var/secret handling). See
  [`tests/lib/geocode_maps/golden/collect.py`](../../tests/lib/geocode_maps/golden/collect.py):45-49
  and [`tests/lib/stt/golden/collect.py`](../../tests/lib/stt/golden/collect.py):159-163.
- **Delegating WITH callbacks** (ai, divination): the script calls the real
  `lib.aurumentation.collector.collectGoldenData` **and** passes its SDK patcher
  as `aenterCallback`/`aexitCallback`. See
  [`tests/lib/divination/golden/collect.py`](../../tests/lib/divination/golden/collect.py):115-122
  and [`tests/lib/ai/golden/collect.py`](../../tests/lib/ai/golden/collect.py):162-169.

New suites should use the **delegating** style (ideally with callbacks if a
custom patcher is needed) — it is the only way to get the `aenter`/`aexit` hooks
and the only style that stays in sync with library changes.

A shared loader helper exists at
[`tests/lib/aurumentation/test_helpers.py`](../../tests/lib/aurumentation/test_helpers.py):
`baseGoldenDataProvider(path)` constructs a `GoldenDataProvider`, calls
`loadAllScenarios()`, and returns it. Consumer tests wrap it in a session-scoped
fixture ([`tests/lib/yandex_search/golden/test_golden.py`](../../tests/lib/yandex_search/golden/test_golden.py):17-20).

**When NOT to merge — per-fixture parametrisation.** The
`baseGoldenDataProvider` + merged-meta-scenario pattern (above) is fine when you
don't care which individual fixture serves a given call. But suites whose
scenarios are **independent per-call lifecycles** (each with its own
submit → poll → fetch → delete, where two recordings can have near-identical
request signatures) should parametrise **per fixture** instead — merging all
recordings into one flat list shares a single advancing cursor across fixtures
whose request signatures overlap (§8.3), so the lifecycles would interleave
rather than replay independently. The STT golden suite
([`tests/lib/stt/golden/test_golden.py`](../../tests/lib/stt/golden/test_golden.py))
is the worked example: each scenario gets its own `GoldenDataReplayer(fixture)`.

**Recovering non-JSON binary inputs from the fixture.** If a client's request
body depends on a **non-JSON binary input** (e.g. raw audio bytes), that input
cannot be committed alongside the fixture (binary files are typically
`.gitignore`'d). CI replay must therefore **recover those bytes from the
committed fixture itself**: the recorded request body carries the binary
content (base64-encoded inside the JSON body), which is NOT secret-masked
(base64 cannot contain the literal API-key substring). The replay test
base64-decodes the relevant field and feeds the bytes to the code under test —
it never reads the gitignored local file. The STT golden suite is the worked
example: it recovers audio bytes from the recorded `recognizeFileAsync` POST
body's `content` field (see
[`tests/lib/stt/golden/test_golden.py`](../../tests/lib/stt/golden/test_golden.py),
`_recoverAudioBytesFromFixture`).

### 6.3 Special-case adapter A — the OpenAI SDK patcher

The `openai` Python SDK builds its own `httpx.AsyncClient` via
`openai._base_client.AsyncHttpxClientWrapper`, so patching `httpx.AsyncClient`
alone does **not** intercept it. The AI suite ships a second patcher at
[`tests/lib/ai/golden/openai_patcher.py`](../../tests/lib/ai/golden/openai_patcher.py)
with `OpenAIRecorderPatcher` (for recording) and `OpenAIReplayerPatcher` (for
replay). Each swaps `AsyncHttpxClientWrapper` for a subclass that forces the
recorder's/replayer's `transport` ([`openai_patcher.py`](../../tests/lib/ai/golden/openai_patcher.py):35-47,
70-98).

Wiring:

- **Record:** the `collect.py` passes `patchOpenAI`/`unpatchOpenAI` as the
  recorder callbacks ([`tests/lib/ai/golden/collect.py`](../../tests/lib/ai/golden/collect.py):167-168).
- **Replay:** the test passes `patch`/`unpatch` as the replayer callbacks
  ([`tests/lib/ai/golden/test_golden.py`](../../tests/lib/ai/golden/test_golden.py):51).

General lesson: any client that **hides** `httpx` behind its own subclass needs
a dedicated patcher wired through the callback hooks. (The YC **gRPC SDK**
provider cannot be recorded at all — it isn't httpx-based; the AI collector
explicitly skips it, [`tests/lib/ai/golden/collect.py`](../../tests/lib/ai/golden/collect.py):129-131.)

### 6.4 Special-case adapter B — non-JSON inputs (the scenario runner)

The collector's scenario shape is rigid: it imports `module.class` and calls
`method(**kwargs)`. When the thing you want to exercise needs **constructed
objects** as inputs (not just JSON-serialisable kwargs), you write a thin
**scenario-runner class** that:

1. Accepts the provider/model config in `__init__` (so it flows through
   `init_kwargs` and `${VAR}` substitution), and
2. Exposes a single `async` method taking only JSON kwargs that internally
   builds the real objects and runs the round-trip.

`DivinationScenarioRunner` ([`tests/lib/divination/golden/scenario_runner.py`](../../tests/lib/divination/golden/scenario_runner.py):222)
is the template: `__init__` stands up a one-model LLM provider from config;
`runReading(*, systemId, layoutId, rngSeed, userName, question, lang)`
([scenario_runner.py](../../tests/lib/divination/golden/scenario_runner.py):300)
resolves the divination system + layout, draws symbols deterministically from
the pinned `rngSeed`, builds the prompt messages, and calls the model. The
scenario's `module`/`class`/`method` then point at this runner, so the generic
`collectGoldenData` can drive it with **no custom collector code**
([scenario_runner.py](../../tests/lib/divination/golden/scenario_runner.py):9-13).

The divination replayer test
([`tests/lib/divination/golden/test_golden.py`](../../tests/lib/divination/golden/test_golden.py))
also demonstrates two extra techniques worth copying:

- **Two-tier tests.** Always-on "sanity" tests validate `scenarios.json`
  itself (required keys, layout resolution, unique names) with no fixtures
  required ([test_golden.py](../../tests/lib/divination/golden/test_golden.py):83);
  the replayer test is parametrised over `findGoldenDataFiles(data/)` and emits
  zero cases when `data/` is empty.
- **Re-deriving the result.** Because the collector discards the return value
  (§4.1 step 7), the replay test re-runs the **deterministic** part (prompt
  building from the pinned `rngSeed`) and asserts byte-equality against values
  stored in the fixture metadata (§8.5).

---

## 7. Masking model — exactly what gets scrubbed

`SecretMasker` ([`masker.py`](../../lib/aurumentation/masker.py):14) takes a
list of **literal secret strings** plus a list of **key-name regex patterns**
(`DEFAULT_PATTERNS`, [`masker.py`](../../lib/aurumentation/masker.py):28-37).
It applies two distinct mechanisms:

| Mechanism | Where applied | What it does |
|---|---|---|
| **Exact-substring replace** (`maskText`, [`masker.py`](../../lib/aurumentation/masker.py):54) | request `url`, request `body`, response `content` | Replaces each literal secret string with `***MASKED***`. **Not** JSON-aware. |
| **Key-based replace** (`maskDict`/`_isSecretKey`, [`masker.py`](../../lib/aurumentation/masker.py):74,139) | request/response `headers`, request `params` | Any value whose **key** matches a pattern → whole value becomes `***MASKED***`, regardless of type. Recurses into nested dicts/lists. |

Consequences (all load-bearing gotchas):

- **Response bodies are only substring-masked**, never key-masked. A response
  like `{"token": "abc"}` is scrubbed only if `"abc"` is in the explicit
  `secrets` list; the key `token` does **not** trigger masking inside the
  content string. Audio/transcript/long-form content is likewise only masked
  where a literal secret substring appears.
- **The default `key` pattern is extremely broad** — it matches any key
  containing the substring `key` (case-insensitive). Legitimate non-secret
  headers/params whose names contain `key` will have their values blanked.
- Masking is the only secret defence. Always `grep` the generated `data/`
  files for known secret prefixes before committing (the testing.md workflow
  ends with exactly this check).

---

## 8. Gotchas

These are the traps that will cost time if ignored. Each is grounded in source.

### Record/replay patching and matching traps

1. **The global patch is neither re-entrant nor concurrency-safe.** Both
   `GoldenDataRecorder.__aenter__` ([`recorder.py`](../../lib/aurumentation/recorder.py):79-89)
   and `GoldenDataReplayer.__aenter__` ([`replayer.py`](../../lib/aurumentation/replayer.py):79-87)
   reassign the **module-global** `httpx.AsyncClient` and restore the stashed
   original on exit. Nested or overlapping recorder/replayer contexts will
   clobber each other's "original". Do not nest them and do not run them
   concurrently (e.g. under `asyncio.gather`). The restore in `__aexit__` is
   also skipped if the process is killed mid-block.

2. **Replay matching is exact-bytes-with-limited-wildcarding.** `ReplayTransport`
   matches on method + full URL + params + body
   ([`transports.py`](../../lib/aurumentation/transports.py):206-213). The
   `***MASKED***` placeholder is wildcarded **only** in the URL and body
   (regex `[^&]*`) and for the single param key `appid`
   ([`transports.py`](../../lib/aurumentation/transports.py):146-157 — note the
   hardcoded OpenWeatherMap `appid` special case). Everything else must match
   byte-for-byte. If your client changes a header, reorders query params, or
   alters JSON whitespace, replay will raise `ValueError: No recorded call
   found`.

3. **Replay advances through matched recordings and raises on exhaustion; `verifyAllCallsUsed` is still a stub.**
   `ReplayTransport.handle_async_request`
   ([`transports.py`](../../lib/aurumentation/transports.py):195-281) collects
   EVERY recording matching the incoming request signature (method + URL +
   params + body, with `***MASKED***` wildcards) and returns them in
   **record-order on successive calls** for the same signature, via a
   per-signature advancing cursor
   ([`transports.py`](../../lib/aurumentation/transports.py):117). This models
   a sequence of identical-URL responses — e.g. a polling lifecycle whose
   `done:false` → `done:true` polls share a URL. Single-match signatures (the
   common case: every existing golden suite records each signature at most
   once) always resolve to their one recording, so behaviour is unchanged for
   them. When a multi-match sequence is exhausted (more requests issued than
   recorded), it **raises `ValueError` loudly** rather than silently clamping
   — in a correct replay the consumer stops at the terminal recorded response
   (e.g. `done:true`), so exhaustion can only mean an over-polling regression,
   which a shared regression-catching library must surface; since
   `verifyAllCallsUsed` is a stub, this raise is the over-polling signal. (If
   the extra request is legitimate, record one more response rather than
   silencing the raise.) `GoldenDataReplayer.verifyAllCallsUsed()`
   ([`replayer.py`](../../lib/aurumentation/replayer.py):137-148) remains an
   acknowledged **stub** — it only checks `len(recordings) > 0`, i.e. "any
   recording exists", not "all were consumed". Do not rely on it for coverage
   assertions.

### Collector, fixture-storage, and CLI traps

4. **The collector discards the return value.** Only `type(result).__name__`
   is stored ([`collector.py`](../../lib/aurumentation/collector.py):175). At
   replay you cannot diff the full result object; you must either (a) only
   assert on what the client re-derives from the replayed HTTP response, or
   (b) store extra expected values in metadata yourself and re-run the
   deterministic portion of the code under test (the divination pattern, §6.4).

5. **`init_kwargs`/`kwargs` are stored with `${VAR}` placeholders, not
   resolved values** ([`collector.py`](../../lib/aurumentation/collector.py):173-174).
   This is intentional (keeps secrets out of fixtures) but means a replay test
   cannot `cls(**metadata["init_kwargs"])` directly — the placeholders won't
   resolve in CI. The divination test works around this by looking the
   scenario up in `input/scenarios.json` and substituting a sentinel key
   ([`tests/lib/divination/golden/test_golden.py`](../../tests/lib/divination/golden/test_golden.py):214-223).

6. **`saveGoldenData` writes exactly the metadata you pass** — it does **not**
   call `createScenario` or inject `createdAt`/`functionName`
   ([`recorder.py`](../../lib/aurumentation/recorder.py):218-239). The on-disk
   shape is whatever the collector assembled. `createScenario`
   ([`recorder.py`](../../lib/aurumentation/recorder.py):162) is a separate,
   richer builder that the current collector path does not use.

7. **Compression headers are stripped on save.** `getRecordedRecordings`
   removes `content-encoding` and `content-length` from recorded response
   headers ([`recorder.py`](../../lib/aurumentation/recorder.py):143-150)
   because the stored `content` is already decompressed. If you ever bypass
   `getRecordedRecordings` and write recordings by hand, you must do the same
   or replay will hand httpx decompressed bytes labelled as compressed.

8. **Two CLI entry points exist and they behave differently.**
   - `python -m lib.aurumentation.collector` (the `main()` in
     [`collector.py`](../../lib/aurumentation/collector.py):186) resolves
     `--secrets` as **env-var names** and drives the generic `collectGoldenData`.
     [`testing.md`](testing.md) §6 points here.
   - `python -m lib.aurumentation.cli` (the `main()` in
     [`cli.py`](../../lib/aurumentation/cli.py):70) treats `--secrets` as
     **literal secret values** ([`cli.py`](../../lib/aurumentation/cli.py):56-67),
     validates a `--module`/`--function` that the collector then ignores (the
     scenario JSON drives the actual imports), and reports a hardcoded
     `failed_scenarios: 0` ([`cli.py`](../../lib/aurumentation/cli.py):154-160).

   In practice **neither** is what consumers run — they run the per-service
   `collect.py` scripts (§6). Prefer the per-service script; if you do use a
   library CLI, use `collector`, not `cli`.

9. **`RecordingTransport`/`ReplayTransport` print to stdout.** The recorder
   emits debug lines on every request ([`transports.py`](../../lib/aurumentation/transports.py):50,82)
   and on patch/restore ([`recorder.py`](../../lib/aurumentation/recorder.py):71,83,97,123).
   Expect noisy output during recording; it is informational only.

10. **The library has no unit tests of its own.** `tests/lib/aurumentation/`
    contains only [`test_helpers.py`](../../tests/lib/aurumentation/test_helpers.py)
    (shared consumer helpers) and `__init__.py`. The library is exercised
    solely through the five consumer suites. When changing transport/masking
    logic, run **all** golden suites (`./venv/bin/pytest tests/lib -k golden`),
    not a single one.

---

## 9. See also

- [`testing.md`](testing.md) §6 — **user-facing golden-data workflow**:
  how to write a replay test, how to run a collector, the secret-`grep`
  verification step. Read this first if you are *using* the system rather than
  maintaining it.
- [`docs/archive/design/golden-data-testing-system-v2.md`](../archive/design/golden-data-testing-system-v2.md)
  — the v2 design doc (marked implemented): the httpx-patching approach
  comparison, component rationale, and why transport-level patching was chosen
  over `unittest.mock` / `respx` / `pytest-httpx`.
- [`docs/archive/design/ai-aurumentation-design.md`](../archive/design/ai-aurumentation-design.md)
  — design notes for the AI-provider recording path (the SDK-patcher adapter,
  §6.3).
- [`docs/llm/libraries.md`](libraries.md) — overview of `lib/` packages.
- [`AGENTS.md`](../../AGENTS.md) — repo conventions (camelCase, docstrings,
  `./venv/bin/python3`).
