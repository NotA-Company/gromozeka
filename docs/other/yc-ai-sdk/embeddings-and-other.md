# Yandex Cloud AI Studio SDK Reference — Embeddings, Classifiers, Search, Tuning, Datasets, Batch (verified against pinned v0.22.0, 2026-07-18)

All remaining SDK domains beyond completions, image generation, tools, speech,
and chat.

> **Mostly verified against pinned SDK v0.22.0** (re-captured 2026-07-18 from
> `venv/lib/python3.14/site-packages/yandex_ai_studio_sdk/`). **None of these 6
> domains are wired in production** — the embedding path uses
> [`lib/ai/providers/fastembed_provider.py`](../../../lib/ai/providers/fastembed_provider.py)
> (local ONNX via fastembed). Claims marked with ⚠ are server-side facts not
> checkable from the SDK source. See also
> [`gap-analysis.md`](gap-analysis.md) for the gap analysis.

Conventions in code samples match the SDK's own style (snake_case). Factory and
method signatures reflect `_models/text_embeddings/`, `_models/text_classifiers/`,
`_search_api/`, `_search_indexes/`, `_tuning/`, `_datasets/`, `_batch/` as
shipped in v0.22.0. Where a parameter is shown as `= UNDEFINED`, that is the
SDK's `Undefined` sentinel (from `yandex_ai_studio_sdk._types.misc`) meaning
"argument not passed / leave the existing config value unchanged"; the effective
*stored* default for the matching config field is stated in each table.

---

## Text Embeddings

### Creating an Embedding Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# By model name
model = sdk.models.text_embeddings("text-search-doc")

# With well-known aliases (resolved by the SDK, see table below)
model = sdk.models.text_embeddings("doc")     # -> text-search-doc
model = sdk.models.text_embeddings("query")   # -> text-search-query

# Full URI is also accepted (anything containing "://")
model = sdk.models.text_embeddings("emb://b1g.../text-search-doc/latest")
```

Factory signature: `sdk.models.text_embeddings(model_name, *, model_version='latest')`.
If `model_name` contains `://` it is treated as a full URI verbatim; otherwise
the SDK builds `emb://<folder_id>/<model_name>/<model_version>` (applying
well-known name substitution first).

### URI Format

`emb://<folder_id>/<model_name>/<model_version>`

Well-known name aliases (defined in `_models/text_embeddings/function.py`):

| Alias | Resolves To |
|---|---|
| `doc` | `text-search-doc` |
| `query` | `text-search-query` |

⚠ Whether `text-search-doc` / `text-search-query` are reachable under a given
folder is a server-side fact; the SDK only constructs the URI.

### Configuration

```python
model = sdk.models.text_embeddings("doc").configure(
    dimensions=256,  # output dimensionality; None = model default
)
```

`TextEmbeddingsModelConfig` (`_models/text_embeddings/config.py`):

| Parameter | Type | Stored default | Description |
|---|---|---|---|
| `dimensions` | `int \| None` | `None` | Output vector dimensionality |

The `configure(*, dimensions=UNDEFINED)` *parameter* defaults to the `UNDEFINED`
sentinel (no override); passing an `int` or `None` overrides the stored value.

### Execution

```python
# Generate embedding
result: TextEmbeddingsModelResult = await model.run(
    "Hello, world!",
    timeout=60,
    # dimensions=UNDEFINED  # default; inherits the configured value.
    # Pass an int or None here only to override per-call.
)

# Access embedding vector
embedding: tuple[float, ...] = result.embedding
num_tokens: int = result.num_tokens
model_version: str = result.model_version
```

`run()` signature: `run(text, *, timeout=60, dimensions=UNDEFINED)`. Note the
per-call `dimensions` default is `UNDEFINED` (use the configured value), **not**
`None` — passing `None` explicitly means "no dimensionality constraint".

### TextEmbeddingsModelResult

```python
@dataclass(frozen=True)
class TextEmbeddingsModelResult(TupleSequence[float], BaseProtoResult):
    embedding: tuple[float, ...]  # the embedding vector
    num_tokens: int               # tokens processed by the model
    model_version: str            # model version used
```

The class also inherits `TupleSequence[float]`, so the result is iterable /
indexable as a sequence of floats, and defines `__array__()` so
`numpy.array(result)` works (copy is always made; `copy=False` raises).

### Tuning

Embedding models support fine-tuning with `pair` or `triplet` tuning types.
`embeddings_tune_type` is **required** (no default):

```python
tuned_model = await model.tune(
    train_datasets,
    embeddings_tune_type="pair",   # "pair" | "triplet"  (required)
    validation_datasets=UNDEFINED,
    name=UNDEFINED,
    description=UNDEFINED,
    labels=UNDEFINED,
    seed=UNDEFINED,
    lr=UNDEFINED,
    n_samples=UNDEFINED,
    additional_arguments=UNDEFINED,
    dimensions=UNDEFINED,          # Sequence[int], embeddings-specific
    tuning_type=UNDEFINED,
    scheduler=UNDEFINED,
    optimizer=UNDEFINED,
    timeout=60,
    poll_timeout=259200,           # 72h default
    poll_interval=60,
)
```

`poll_timeout` default is `72 * 60 * 60` (259200 s ≈ 3 days), `poll_interval`
default is `60` s. `tune_deferred(...)` and `attach_tune_deferred(task_id, *,
timeout=60)` follow the same parameter shape minus the two poll args.

### Via Chat Domain (OpenAI-Compatible)

The chat domain exposes a *separate* embeddings model that talks to the
OpenAI-compatible HTTP endpoint rather than gRPC:

```python
model = sdk.chat.text_embeddings("text-search-doc")
result = await model.run("Hello, world!", timeout=180)
```

The chat factory (`_chat/text_embeddings/function.py`) does **not** apply the
`doc`/`query` well-known aliases — it builds `emb://<folder>/<name>/latest`
directly. Prefer the full model name (`text-search-doc`) here; ⚠ whether an
alias resolves is a server-side fact.

`run()` signature: `run(input, *, timeout=180)` where
`input: str | Sequence[str]` (a list of strings is accepted; the HTTP endpoint
returns a single embedding for the batch). Default timeout is **180 s**, not 60.

`ChatEmbeddingsModelConfig` (`_chat/text_embeddings/config.py`) extends the gRPC
config and adds:

| Parameter | Type | Stored default | Description |
|---|---|---|---|
| `dimensions` | `int \| None` | `None` | Output dimensionality |
| `encoding_format` | `Literal['float'] \| None` | `None` | Only `'float'` is supported |
| `extra_query` | `QueryType \| None` | `None` | Extra query params merged into the request body |

Result type is **`ChatEmbeddingsModelResult`** (not the gRPC result):

```python
@dataclass(frozen=True)
class ChatEmbeddingsModelResult(TupleSequence[float], BaseJsonResult):
    embedding: tuple[float, ...]
    model: str                       # URI of the model used
    usage: EmbeddingsUsage | None    # input_text_tokens / prompt_tokens alias, total_tokens
```

There is no `num_tokens` / `model_version` field on the chat result.

---

## Text Classifiers

### Creating a Classifier Model

```python
model = sdk.models.text_classifiers("yandexgpt")
# URI: cls://<folder_id>/yandexgpt/latest
```

Factory signature: `sdk.models.text_classifiers(model_name, *, model_version='latest')`.
URI scheme: `cls://`. There are no well-known name aliases for classifiers.

⚠ Whether `"yandexgpt"` (or any other name) is a valid classifier model under a
folder is server-side; the SDK only builds the URI.

### Configuration

```python
model = sdk.models.text_classifiers("yandexgpt").configure(
    task_description="Classify the sentiment of the text",
    labels=["positive", "negative", "neutral"],
    samples=[
        {"text": "I love this!", "label": "positive"},
        {"text": "This is terrible", "label": "negative"},
    ],
)
```

`TextClassifiersModelConfig` (`_models/text_classifiers/config.py`):

| Parameter | Type | Stored default | Description |
|---|---|---|---|
| `task_description` | `str \| None` | `None` | Description of the classification task |
| `labels` | `Sequence[str] \| None` | `None` | Classification labels |
| `samples` | `Sequence[TextClassificationSample] \| None` | `None` | Few-shot examples |

`TextClassificationSample` is a `TypedDict` with `text: str` and `label: str`.

**Behavior** (verified in `_models/text_classifiers/model.py`): if **any** of
`task_description` / `labels` / `samples` is non-`None`, the model routes to
few-shot classification (`FewShotClassify` RPC). Within that path, both
`task_description` **and** `labels` must be non-`None` (else `ValueError`);
`samples` is optional and defaults to empty. If all three are `None`, the model
uses zero-shot classification (`Classify` RPC) — only available for pre-trained
models.

### Execution

```python
result: TextClassifiersModelResultBase = await model.run(
    "This product is amazing!",
    timeout=60,
)

for prediction in result.predictions:
    print(f"Label: {prediction['label']}, Confidence: {prediction['confidence']}")
```

`run()` signature: `run(text, *, timeout=60)`.

### TextClassifiersModelResult

```python
@dataclass(frozen=True)
class TextClassifiersModelResultBase(TupleSequence[TextClassificationLabel], BaseProtoResult):
    predictions: tuple[TextClassificationLabel, ...]
    model_version: str
    input_tokens: int
```

`TextClassificationLabel` is a frozen `Mapping` with `label: str` and
`confidence: float`, so `prediction['label']` / `prediction['confidence']`
work (as do attribute access and iteration). Two concrete subclasses:
`TextClassifiersModelResult` (zero-shot) and `FewShotTextClassifiersModelResult`
(few-shot) — both are empty subclasses of the base, differing only in their
proto response type.

### Tuning

`classification_type` is **required** (no default):

```python
tuned_model = await model.tune(
    train_datasets,
    classification_type="multilabel",  # "multilabel" | "multiclass" | "binary" (required)
    validation_datasets=UNDEFINED,
    name=UNDEFINED,
    description=UNDEFINED,
    labels=UNDEFINED,
    seed=UNDEFINED,
    lr=UNDEFINED,
    n_samples=UNDEFINED,
    additional_arguments=UNDEFINED,
    tuning_type=UNDEFINED,
    scheduler=UNDEFINED,
    optimizer=UNDEFINED,
    timeout=60,
    poll_timeout=259200,  # 72h default
    poll_interval=60,
)
```

`ClassificationTuningTypes = Literal['multilabel', 'multiclass', 'binary']`.
`tune_deferred(...)` / `attach_tune_deferred(task_id, *, timeout=60)` follow the
same shape minus the two poll args.

---

## Search API

Exposed as `sdk.search_api` (`_search_api/domain.py`). Five subdomains:

| Subdomain | Factory |
|---|---|
| `generative` | `sdk.search_api.generative(*, site=, host=, url=, fix_misspell=, enable_nrfm_docs=, search_filters=)` |
| `web` | `sdk.search_api.web(search_type, *, family_mode=, ...)` |
| `image` | `sdk.search_api.image(search_type, *, family_mode=, format=, size=, ...)` |
| `by_image` | `sdk.search_api.by_image(*, family_mode=, site=)` |
| `wordstat` | `sdk.search_api.wordstat()` |

### Generative Search

AI-summarized answers with source citations:

```python
gen_search = sdk.search_api.generative(
    site=UNDEFINED,              # str | Sequence[str]; mutually exclusive with host/url
    host=UNDEFINED,              # str | Sequence[str]
    url=UNDEFINED,               # str | Sequence[str]
    fix_misspell=UNDEFINED,      # bool
    enable_nrfm_docs=UNDEFINED,  # bool
    search_filters=UNDEFINED,    # Sequence[dict] e.g. [{'date': '<20250101'}, {'lang': 'ru'}, {'format': 'doc'}]
)

result = await gen_search.run("What is YandexGPT?", timeout=60)
```

`site`, `host`, `url` are **mutually exclusive** (the SDK raises
`AIStudioConfigurationError` if more than one is set). If none is provided, the
search ⚠ runs across the entire Yandex index (server-side behavior). Each filter
dict in `search_filters` must have exactly one key from `{'date', 'lang', 'format'}`;
`format` values must be in `gen_search.available_formats` (exposed as a property
on the factory).

`run()` accepts a string, a `{"text": ..., "role": ...}` dict, any object with
`.text`/`.role` attributes, or a sequence of any of these (conversation context).
Default timeout 60 s. Returns `GenerativeSearchResult` (fields: `text`,
`role`, `fixed_misspell_query`, `is_answer_rejected`, `is_bullet_answer`,
`sources: tuple[SearchSource, ...]`, `search_queries: tuple[SearchQuery, ...]`;
`SearchSource` has `url`, `title`, `used`).

Can also be used as a tool (see
[Tools & Structured Output](tools-and-structured-output.md)):

```python
tool = gen_search.as_tool(description="Search the web for current information")
```

`as_tool(description: str)` — raises `ValueError` if `fix_misspell` is set on
the source config (that option is unsupported on the tool path).

### Web Search

Paginated web search results:

```python
web_search = sdk.search_api.web(
    "RU",                # search_type (required, positional)
    family_mode=UNDEFINED,
    fix_typo_mode=UNDEFINED,
    localization=UNDEFINED,
    sort_order=UNDEFINED,
    sort_mode=UNDEFINED,
    group_mode=UNDEFINED,
    groups_on_page=UNDEFINED,
    docs_in_group=UNDEFINED,
    max_passages=UNDEFINED,
    region=UNDEFINED,
    user_agent=UNDEFINED,
    metadata=UNDEFINED,
)

result = await web_search.run("YandexGPT documentation", timeout=60)
```

`search_type` accepted string values (`SearchType` in `_search_api/enums.py`):
`RU | TR | COM | KK | BE | UZ`. `BY` is accepted as an alias for `BE`
(`__aliases__ = {'BY': 'BE', ...}` in the enum); there is **no** `BY`/`KZ`
member. Enum-typed kwargs (`family_mode`, `fix_typo_mode`, `localization`,
`sort_order`, `sort_mode`, `group_mode`) accept strings, ints, or the enum
member and are coerced via `ProtoBasedEnum._coerce`.

`run(query, *, format='parsed', page=0, timeout=60)` — `format` is
`Literal['parsed', 'xml', 'html']`; with `'parsed'` (default) returns an
`AsyncWebSearchResult` / `WebSearchResult`, with `'xml'`/`'html'` returns raw
`bytes`. **Web search also supports `run_deferred(query, *, format, page,
timeout)`** which returns an `AsyncOperation[...]` (see AsyncOperation pattern
below). The parsed result exposes `.docs`, `.groups`, `.xml`, `.page`, and
`.next_page(...)` / `.next_page_deferred(...)` for pagination.

### Image Search

Search images by text query:

```python
image_search = sdk.search_api.image(
    "RU",                # search_type (required, positional)
    family_mode=UNDEFINED,
    fix_typo_mode=UNDEFINED,
    format=UNDEFINED,    # ImageFormat: JPEG | GIF | PNG
    size=UNDEFINED,      # ImageSize: ENORMOUS | LARGE | MEDIUM | SMALL | TINY | WALLPAPER
    orientation=UNDEFINED,  # ImageOrientation: VERTICAL | HORIZONTAL | SQUARE
    color=UNDEFINED,     # ImageColor: COLOR | GRAYSCALE | RED | ORANGE | YELLOW | GREEN | CYAN | BLUE | VIOLET | WHITE | BLACK
    site=UNDEFINED,
    docs_on_page=UNDEFINED,
    user_agent=UNDEFINED,
)

result = await image_search.run("YandexGPT logo", timeout=60)
```

`run(query, *, format='parsed', page=0, timeout=60)` — `format` is
`Literal['parsed', 'xml']` (no `'html'` for image search). Returns
`AsyncImageSearchResult` / `ImageSearchResult` when parsed. No
`run_deferred`.

### By-Image Search (Reverse Image Search)

Search by image content:

```python
by_image_search = sdk.search_api.by_image(
    family_mode=UNDEFINED,
    site=UNDEFINED,
)

with open("photo.jpg", "rb") as f:
    image_bytes = f.read()

result = await by_image_search.run(image_bytes, timeout=60)
```

Three run variants (`_search_api/by_image/by_image.py`):

- `run(image_data: bytes, *, page=0, timeout=60)` — search by raw image bytes.
- `run_from_url(url: str, *, page=0, timeout=60)` — search by image URL.
- `run_from_id(cbir_id: str, *, page=0, timeout=60)` — search by CBIR ID
  returned from a previous by-image search.

Returns `AsyncByImageSearchResult` / `ByImageSearchResult` (fields: `images:
tuple[ByImageSearchDocument, ...]`, `cbir_id`, `page`; `.docs` is an alias for
`.images`; `.next_page(...)` paginates via `cbir_id`). No `run_deferred`.

### Wordstat

Keyword statistics service. Factory takes no parameters:

```python
wordstat = sdk.search_api.wordstat()

regions = await wordstat.get_regions_tree(timeout=60)
top = await wordstat.get_top("yandexgpt", 10, timeout=60)
dynamics = await wordstat.get_dynamics(
    "yandexgpt", "weekly", datetime.date(2024, 1, 1), datetime.date(2024, 6, 1),
    timeout=60,
)
distribution = await wordstat.get_regions_distribution("yandexgpt", timeout=60)
```

`get_top(phrase, num_phrases, *, regions=UNDEFINED, devices=UNDEFINED,
timeout=60)`; `get_dynamics(phrase, period, from_date, to_date, *, regions=,
devices=, timeout=60)` where `period` is `PeriodType`
(`MONTHLY | WEEKLY | DAILY`); `get_regions_distribution(phrase, *,
distribution_type=UNDEFINED, devices=UNDEFINED, resolve_regions=False,
timeout=60)` where `distribution_type` is `RegionsDistributionType`
(`ALL | CITIES | REGIONS`). `devices` accepts `DeviceType`
(`ALL | DESKTOP | PHONE | TABLET`).

Wordstat does not have a `.run()` method, so it is omitted from the Method
Availability Summary below.

---

## Search Indexes

Vector/hybrid/text search indexes for RAG applications. Exposed as
`sdk.search_indexes` (`_search_indexes/domain.py`).

```python
from yandex_ai_studio_sdk._search_indexes.index_type import (
    TextSearchIndexType, VectorSearchIndexType, HybridSearchIndexType,
)

# Create a search index (deferred — returns an AsyncOperation[AsyncSearchIndex])
operation = await sdk.search_indexes.create_deferred(
    files=["file-id-1", "file-id-2"],   # file IDs, BaseFile instances, or a mix
    index_type=TextSearchIndexType(),   # instance of BaseSearchIndexType (NOT a string)
    name="my-index",
    description="My search index",
    labels=UNDEFINED,
    ttl_days=UNDEFINED,                 # must be paired with expiration_policy
    expiration_policy=UNDEFINED,        # 'static' | 'since_last_active'
    timeout=60,
)
index = await operation  # await the operation to get the AsyncSearchIndex

# Get existing index
index = await sdk.search_indexes.get("index-id", timeout=60)

# List indexes
async for index in sdk.search_indexes.list(page_size=100, timeout=60):
    print(index.id)
```

`index_type` **must be an instance** of `BaseSearchIndexType` — a bare string
like `"BM25"` raises `TypeError('index type must be instance of
BaseSearchIndexType')`. The three concrete types (in
`_search_indexes/index_type.py`) are:

- `TextSearchIndexType(*, chunking_strategy=None)` — keyword/BM25-style text
  index (the closest thing to a "BM25" index in this SDK).
- `VectorSearchIndexType(*, doc_embedder_uri=None, query_embedder_uri=None, chunking_strategy=None)`.
- `HybridSearchIndexType(*, text_search_index=None, vector_search_index=None, normalization_strategy=None, combination_strategy=None, chunking_strategy=None)`.

`ttl_days` and `expiration_policy` must be **both defined or both undefined**
(the SDK raises `ValueError` otherwise). `create_deferred` returns an
`AsyncOperation[AsyncSearchIndex]`, not an index directly.

Methods on the returned `AsyncSearchIndex` / `SearchIndex` object
(`_search_indexes/search_index.py`):

- `update(*, name=, description=, labels=, ttl_days=, expiration_policy=, timeout=60)`
- `delete(*, timeout=60)`
- `get_file(file_id, *, timeout=60)`
- `list_files(*, page_size=, timeout=60)` (async iterator)
- `add_files_deferred(files, *, timeout=60)` → `AsyncOperation[tuple[SearchIndexFile, ...]]`

There is **no `.query(...)` method** on `SearchIndex` — querying an index is
done through the Assistants API, not via this object. `RichSearchIndex` fields:
`folder_id`, `name`, `description`, `created_by`, `created_at`, `updated_by`,
`updated_at`, `expires_at`, `labels`, `index_type`.

---

## Tuning (Fine-Tuning)

Fine-tuning is available for `GPTModel` (completions), `TextEmbeddingsModel`,
and `TextClassifiersModel`. The tuning *domain* (`sdk.tuning`) manages tasks;
tuning itself is initiated from a model instance.

### Tuning via Model Methods

```python
# Deferred tuning — returns an AsyncTuningTask[...] without polling
tuning_task = await model.tune_deferred(
    train_datasets,
    # Embedding models require: embeddings_tune_type="pair" | "triplet"
    # Classifier models require: classification_type="multilabel" | "multiclass" | "binary"
    validation_datasets=UNDEFINED,
    name=UNDEFINED,
    description=UNDEFINED,
    labels=UNDEFINED,
    seed=UNDEFINED,
    lr=UNDEFINED,
    n_samples=UNDEFINED,
    additional_arguments=UNDEFINED,
    tuning_type=UNDEFINED,
    scheduler=UNDEFINED,
    optimizer=UNDEFINED,
    timeout=60,
)
tuned_model = await tuning_task  # await the task to poll + resolve

# Blocking tuning (polls until complete, returns the tuned model directly)
tuned_model = await model.tune(
    train_datasets,
    embeddings_tune_type="pair",   # OR classification_type="multilabel", etc. (required)
    ...,
    poll_timeout=259200,  # 72h default
    poll_interval=60,
)

# Re-attach to an existing tuning task by id
task = await model.attach_tune_deferred("task-id", timeout=60)
```

### Tuning Task Management

```python
# Get a task by id (returns an AsyncTuningTask, NOT a TuningTaskInfo)
task = await sdk.tuning.get("task-id", timeout=60)

# List tasks (yields AsyncTuningTask objects)
async for task in sdk.tuning.list(page_size=100, timeout=60):
    print(task.id)                       # .id is the operation_id or task_id
    info = await task.get_task_info(timeout=60)
    print(info.task_id, info.status)
```

The async iterator yields `AsyncTuningTask` objects, which expose `.id` but
**not** `.task_id` / `.status` directly — call `await task.get_task_info(...)`
to get a `TuningTaskInfo` (see below) and read its fields.

### TuningTaskInfo

```python
@dataclass(frozen=True)
class TuningTaskInfo(BaseResource[TuningTaskProto]):
    task_id: str
    operation_id: str
    status: TuningTaskStatusEnum   # STATUS_UNSPECIFIED | CREATED | PENDING | IN_PROGRESS | COMPLETED | FAILED
    folder_id: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    source_model_uri: str
    target_model_uri: str | None
```

`TuningTaskStatusEnum` (`_tuning/tuning_task.py`): `STATUS_UNSPECIFIED (0)`,
`CREATED (1)`, `PENDING (2)`, `IN_PROGRESS (3)`, `COMPLETED (4)`, `FAILED (5)`.

### AsyncTuningTask

```python
task_info = await tuning_task.get_task_info(timeout=60)   # -> TuningTaskInfo | None
metrics_url = await tuning_task.get_metrics_url(timeout=60)  # -> str | None
```

Both return `None` if the task has not yet produced info / metrics. The task
also inherits the standard operation interface (`get_status`, `get_result`,
`cancel`, `wait`, and `await task`).

---

## Datasets

Dataset management for preparing training data. Exposed as `sdk.datasets`
(`_datasets/domain.py`).

```python
# Create a local dataset draft from a file (no server call yet)
draft = sdk.datasets.draft_from_path(
    path="training_data.jsonl",
    task_type="TextToTextGeneration",   # see KnownTaskType below
    upload_format="jsonl",
    name="my-dataset",
    description="Training data for YandexGPT",
    metadata=UNDEFINED,
    labels=UNDEFINED,
    allow_data_logging=UNDEFINED,
)

# Upload the draft (creates the dataset server-side, uploads chunks, validates)
dataset = await draft.upload(
    timeout=60,
    upload_timeout=360,
    raise_on_validation_failure=True,
    poll_timeout=21600,      # DEFAULT_OPERATION_POLL_TIMEOUT = 6 * 60 * 60 (6h)
    poll_interval=60,
    chunk_size=DEFAULT_CHUNK_SIZE,
    parallelism=UNDEFINED,
)
# Or non-blocking: op = await draft.upload_deferred(...); dataset = await op
```

⚠ `task_type` must be a server-recognised task type string. The SDK's
`KnownTaskType` enum (`_datasets/task_types.py`) lists the well-known values:
`TextToTextGeneration`, `TextClassificationMultilabel`,
`TextClassificationMulticlass`, `SpeechToTextGeneration`,
`TextToSpeechGeneration`, `TextToImageGeneration`, `TextEmbeddingsPair`,
`TextEmbeddingsTriplet` (plus `TextToTextGenerationRequest`,
`ImageTextToTextGenerationRequest`). The list is explicitly non-exhaustive —
additional server-side types may be accepted ⚠. `"TextGeneration"` is **not** a
valid value; use `"TextToTextGeneration"` for completions datasets.

Convenience task-type helpers (each returns a `DatasetsWrapper` with
`task_type` pre-bound, exposing `draft_from_path`, `list`, `list_upload_formats`,
`list_upload_schemas`):

| Helper | Bound `task_type` |
|---|---|
| `sdk.datasets.completions` | `TextToTextGeneration` |
| `sdk.datasets.text_classifiers_multilabel` | `TextClassificationMultilabel` |
| `sdk.datasets.text_classifiers_multiclass` | `TextClassificationMulticlass` |
| `sdk.datasets.text_classifiers_binary` | `TextClassificationMultilabel` ⚠ |
| `sdk.datasets.text_embeddings_pair` | `TextEmbeddingsPair` |
| `sdk.datasets.text_embeddings_triplet` | `TextEmbeddingsTriplet` |

⚠ In v0.22.0 `text_classifiers_binary` is bound to `TextClassificationMultilabel`
(see `_datasets/domain.py` line ~49) — this looks like an SDK typo; binary
classification may still work server-side but the bound string is multilabel.

```python
# Get existing dataset
dataset = await sdk.datasets.get("dataset-id", timeout=60)

# List datasets (yields Dataset objects)
async for ds in sdk.datasets.list(status=UNDEFINED, name_pattern=UNDEFINED, task_type=UNDEFINED, timeout=60):
    print(ds.id, ds.name)

# List upload schemas for a task type (returns tuple[DatasetUploadSchema, ...])
schemas = await sdk.datasets.list_upload_schemas("TextToTextGeneration", timeout=60)
# list_upload_formats(...) also exists but is deprecated (DeprecationWarning)
```

---

## Batch

Batch operations for completions (process many requests at once). Exposed as
`sdk.batch` (`_batch/domain.py`).

```python
# Get a batch task by id (first arg accepts str | BatchTaskInfo)
task = await sdk.batch.get("task-id", timeout=60)

# List batch task operations (yields AsyncBatchTaskOperation)
async for op in sdk.batch.list_operations(page_size=100, status=UNDEFINED, timeout=60):
    print(op.id)                          # .id is the task id
    info = await op.get_task_info(timeout=60)
    print(info.task_id, info.status)

# List batch task info directly (yields BatchTaskInfo)
async for info in sdk.batch.list_info(page_size=100, status=UNDEFINED, timeout=60):
    print(info.task_id, info.status)      # NOTE: info has .task_id, not .id
```

`BatchTaskOperation` exposes `.id` / `.task_id` but **not** `.status`
directly — call `await op.get_task_info(...)` (returns `BatchTaskInfo`) or
`await op.get_status(...)` to read status. Conversely, `BatchTaskInfo` has
`.task_id` / `.operation_id` / `.status` but **no** `.id` attribute.

`BatchTaskStatus` (`_types/batch/status.py`): `UNKNOWN`, `STATUS_UNSPECIFIED`,
`CREATED`, `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `CANCELED`.
`BatchTaskInfo` fields: `task_id`, `operation_id`, `folder_id`, `model_uri`,
`source_dataset_id`, `result_dataset_id`, `status`, `labels`, `created_by`,
`created_at`, `started_at`, `finished_at`, `errors`.

### Batch via model instances

Only the completions model (`GPTModel` / `AsyncGPTModel`) mixes in
`BaseModelBatchMixin`. Batch is reached through the model's **`.batch` property**
(not `as_batch()`), which returns a `BatchSubdomain` / `AsyncBatchSubdomain`:

```python
completion_model = sdk.models.completions("yandexgpt")
op = await completion_model.batch.run_deferred(dataset="dataset-id", timeout=60)
```

The subdomain exposes `run_deferred(dataset, *, timeout=60)` (no
`batch_run` / `batch_run_deferred` methods — those names do not exist in
v0.22.0).

---

## AsyncOperation Pattern

Deferred calls (`run_deferred`, `create_deferred`, `tune_deferred`,
`upload_deferred`, `add_files_deferred`) return an `AsyncOperation[T]`
(`_types/operation.py`) that resolves to `T`. The same shape is used everywhere
in the SDK — completions, image generation, search indexes, datasets, tuning,
and batch tasks all share this interface:

```python
op = await model.run_deferred(...)         # AsyncOperation[ResultType]

status = await op.get_status(timeout=60)   # OperationStatus / domain-specific status
result = await op.get_result(timeout=60)   # raises if not done/succeeded
await op.cancel(timeout=60)

result = await op.wait(                     # block until done, then return result
    timeout=60,
    poll_timeout=None,                      # int seconds; None = class default (3600)
    poll_interval=None,                     # float seconds; None = class default (10)
)
# `await op` is sugar for `op.wait()` with default args.
```

`OperationStatus` exposes `.is_running`, `.is_succeeded`, `.is_failed`,
`.is_finished`, `.status_name`. On failure, `get_result` / `wait` raise
`RunError` (built from `OperationErrorInfo`).

---

## Method Availability Summary

Verified against the v0.22.0 model sources. Rows for Completions / Image
Generation / Chat / TTS / STT are verified in their companion files
([Completions](completions.md), [Image Generation](image-generation.md),
speech docs); the embedding / classifier / search rows are verified here.

| Model Type | `run()` | `run_stream()` | `run_deferred()` | `configure()` | `tokenize()` | `tune()` | `tune_deferred()` |
|---|---|---|---|---|---|---|---|
| Completions (gRPC) | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Image Generation | No | No | Yes | Yes | No | No | No |
| Text Embeddings (gRPC) | Yes | No | No | Yes | No | Yes | Yes |
| Text Classifiers (gRPC) | Yes | No | No | Yes | No | Yes | Yes |
| Chat Completions | Yes | Yes | No | Yes | No | No | No |
| Chat Embeddings | Yes | No | No | Yes | No | No | No |
| TTS | Yes | Yes | No | Yes | No | No | No |
| STT | Yes | Yes | Yes | Yes | No | No | No |
| Generative Search | Yes | No | No | Yes | No | No | No |
| Web Search | Yes | No | Yes | Yes | No | No | No |
| Image Search | Yes | No | No | Yes | No | No | No |
| By-Image Search | Yes | No | No | Yes | No | No | No |

Notes:

- Web search `run_deferred(...)` returns `AsyncOperation[AsyncWebSearchResult]`
  (or `AsyncOperation[bytes]` with `format='xml'|'html'`); it is the only search
  subdomain with a deferred run.
- "Yes" for `run()` on By-Image Search means `run(image_data: bytes)` /
  `run_from_url(url)` / `run_from_id(cbir_id)` — there is no string-query form.
- Wordstat is omitted (no `.run()` method; uses `get_top` / `get_dynamics` /
  `get_regions_distribution` / `get_regions_tree`).
- Batch (`sdk.batch`) is a domain, not a model type; completions reach it via
  `model.batch.run_deferred(dataset)`.
