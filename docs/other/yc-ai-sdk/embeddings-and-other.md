# Embeddings, Classifiers, Search API, Tuning, Datasets, Batch

All remaining SDK domains beyond completions, image generation, tools, speech,
and chat.

## Text Embeddings

### Creating an Embedding Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# By model name
model = sdk.models.text_embeddings("text-search-doc")

# With well-known aliases
model = sdk.models.text_embeddings("doc")     # -> text-search-doc
model = sdk.models.text_embeddings("query")   # -> text-search-query
```

### URI Format

`emb://<folder_id>/<model_name>/<model_version>`

Well-known name aliases (resolved automatically):

| Alias | Resolves To |
|---|---|
| `doc` | `text-search-doc` |
| `query` | `text-search-query` |

### Configuration

```python
model = sdk.models.text_embeddings("doc").configure(
    dimensions=256,  # Output dimensionality (None = model default)
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dimensions` | `int \| None` | UNDEFINED | Output vector dimensionality |

### Execution

```python
# Generate embedding
result: TextEmbeddingsModelResult = await model.run(
    "Hello, world!",
    timeout=60,
    dimensions=None,  # Override configured dimensions
)

# Access embedding vector
embedding: tuple[float, ...] = result.embedding
num_tokens: int = result.num_tokens
model_version: str = result.model_version
```

### TextEmbeddingsModelResult

```python
@dataclass(frozen=True)
class TextEmbeddingsModelResult:
    embedding: tuple[float, ...]  # The embedding vector
    num_tokens: int               # Number of tokens in the input
    model_version: str            # Model version used
```

Also supports `numpy.array()` conversion for the embedding vector.

### Via Chat Domain (OpenAI-Compatible)

```python
model = sdk.chat.text_embeddings("doc")
result = await model.run("Hello, world!", timeout=60)
# Same result type
```

### Tuning

Embedding models support fine-tuning with `pair` or `triplet` tuning types:

```python
tuned_model = await model.tune(
    train_datasets,
    embeddings_tune_type="pair",  # or "triplet"
    validation_datasets=None,
    poll_timeout=259200,
    poll_interval=60,
)
```

---

## Text Classifiers

### Creating a Classifier Model

```python
model = sdk.models.text_classifiers("yandexgpt")
# URI: cls://<folder_id>/yandexgpt/latest
```

### URI Format

`cls://<folder_id>/<model_name>/<model_version>`

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

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_description` | `str \| None` | UNDEFINED | Description of the classification task |
| `labels` | `Sequence[str] \| None` | UNDEFINED | Classification labels |
| `samples` | `Sequence[TextClassificationSample] \| None` | UNDEFINED | Few-shot examples |

**Behavior**: If `task_description`/`labels`/`samples` are provided, the model
uses few-shot classification (`FewShotClassify` RPC). Otherwise, it uses
zero-shot classification (`Classify` RPC).

### Execution

```python
result: TextClassifiersModelResultBase = await model.run(
    "This product is amazing!",
    timeout=60,
)

for prediction in result.predictions:
    print(f"Label: {prediction['label']}, Confidence: {prediction['confidence']}")
```

### TextClassifiersModelResult

```python
@dataclass(frozen=True)
class TextClassifiersModelResultBase:
    predictions: tuple[TextClassificationLabel, ...]  # {"label": str, "confidence": float}
    model_version: str
    input_tokens: int
```

Two concrete result types:
- `TextClassifiersModelResult` -- for zero-shot classification
- `FewShotTextClassifiersModelResult` -- for few-shot classification

### Tuning

```python
tuned_model = await model.tune(
    train_datasets,
    classification_type="multiclass",  # "multiclass" | "multilabel" | "binary"
    validation_datasets=None,
    poll_timeout=259200,
    poll_interval=60,
)
```

---

## Search API

### Generative Search

AI-summarized answers with source citations:

```python
gen_search = sdk.search_api.generative(
    site=None,              # Restrict to site(s)
    host=None,              # Restrict to host(s)
    url=None,               # Restrict to URL(s)
    fix_misspell=None,      # Auto-fix typos
    enable_nrfm_docs=None,  # Enable NRFM documents
    search_filters=None,    # [{'date': '<20250101'}, {'lang': 'ru'}, {'format': 'doc'}]
)

result = await gen_search.run("What is YandexGPT?", timeout=60)
# result: GenerativeSearchResult with answer text and source links
```

Can also be used as a tool (see [Tools & Structured Output](tools-and-structured-output.md)):

```python
tool = gen_search.as_tool(description="Search the web for current information")
```

### Web Search

Paginated web search results:

```python
web_search = sdk.search_api.web(
    search_type="RU",       # RU | TR | COM | KK (alias BY) | BE | UZ
    family_mode=None,
    fix_typo_mode=None,
    localization=None,
    sort_order=None,
    sort_mode=None,
    group_mode=None,
    groups_on_page=None,
    docs_in_group=None,
    max_passages=None,
    region=None,
    user_agent=None,
    metadata=None,
)

result = await web_search.run("YandexGPT documentation", timeout=60)
```

### Image Search

Search images by text query:

```python
image_search = sdk.search_api.image(
    search_type="RU",
    family_mode=None,
    fix_typo_mode=None,
    format=None,            # Image format filter
    size=None,              # Image size filter
    orientation=None,       # Image orientation filter
    color=None,             # Color filter
    site=None,              # Site restriction
    docs_on_page=None,
    user_agent=None,
)

result = await image_search.run("YandexGPT logo", timeout=60)
```

### By-Image Search (Reverse Image Search)

Search by image content:

```python
by_image_search = sdk.search_api.by_image(
    family_mode=None,
    site=None,
)

with open("photo.jpg", "rb") as f:
    image_bytes = f.read()

result = await by_image_search.run(image_bytes, timeout=60)
```

---

## Search Indexes

Vector/hybrid search indexes for RAG applications:

```python
# Create a search index (deferred)
operation = await sdk.search_indexes.create_deferred(
    files=["file-id-1", "file-id-2"],
    index_type="BM25",           # Index type
    name="my-index",
    description="My search index",
    labels=None,
    ttl_days=None,               # Time-to-live in days
    expiration_policy=None,
    timeout=60,
)

# Get existing index
index = await sdk.search_indexes.get("index-id", timeout=60)

# List indexes
async for index in sdk.search_indexes.list(page_size=100, timeout=60):
    print(index.id)

# Update, delete, query -- methods available on the SearchIndex object
```

---

## Tuning (Fine-Tuning)

Fine-tuning is available for `GPTModel`, `TextEmbeddingsModel`, and
`TextClassifiersModel`.

### Tuning via Model Methods

```python
# Deferred tuning
tuning_task = await model.tune_deferred(
    train_datasets,
    validation_datasets=None,
    name=None,
    seed=None,
    lr=None,                        # Learning rate
    n_samples=None,                  # Number of samples
    additional_arguments=None,       # Additional tuning arguments
    # Embedding-specific:
    embeddings_tune_type="pair",     # "pair" | "triplet" (embeddings only)
    # Classifier-specific:
    classification_type="multiclass", # "multiclass" | "multilabel" | "binary" (classifiers only)
)

# Blocking tuning (polls until complete)
tuned_model = await model.tune(
    train_datasets,
    ...,
    poll_timeout=259200,  # 3 days max
    poll_interval=60,      # Check every 60s
)
```

### Tuning Task Management

```python
# Get task info
task = await sdk.tuning.get("task-id", timeout=60)

# List tasks
async for task in sdk.tuning.list(page_size=100, timeout=60):
    print(task.task_id, task.status)
```

### TuningTaskInfo

```python
@dataclass(frozen=True)
class TuningTaskInfo:
    task_id: str
    operation_id: str
    status: TuningTaskStatusEnum    # CREATED, PENDING, IN_PROGRESS, COMPLETED, FAILED
    folder_id: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    source_model_uri: str
    target_model_uri: str | None
```

### AsyncTuningTask

```python
# Additional methods on the tuning task:
task_info = await tuning_task.get_task_info(timeout=60)
metrics_url = await tuning_task.get_metrics_url(timeout=60)
```

---

## Datasets

Dataset management for preparing training data:

```python
# Create a dataset draft from a file
draft = sdk.datasets.draft_from_path(
    path="training_data.jsonl",
    task_type="TextGeneration",      # Task type for the dataset
    upload_format="jsonl",
    name="my-dataset",
    description="Training data for YandexGPT",
    metadata=None,
    labels=None,
    allow_data_logging=False,
)

# Convenience task type helpers
sdk.datasets.completions              # Text generation datasets
sdk.datasets.text_classifiers_multilabel
sdk.datasets.text_classifiers_multiclass
sdk.datasets.text_classifiers_binary
sdk.datasets.text_embeddings_pair
sdk.datasets.text_embeddings_triplet

# Get existing dataset
dataset = await sdk.datasets.get("dataset-id", timeout=60)

# List datasets
async for ds in sdk.datasets.list(status=None, name_pattern=None, task_type=None, timeout=60):
    print(ds.id, ds.name)

# List upload schemas
schemas = await sdk.datasets.list_upload_schemas("TextGeneration", timeout=60)
```

---

## Batch

Batch operations for completions (process many requests at once):

```python
# Get batch task
task = await sdk.batch.get("task-id", timeout=60)

# List operations
async for op in sdk.batch.list_operations(page_size=100, status=None, timeout=60):
    print(op.id, op.status)

# List task info
async for info in sdk.batch.list_info(page_size=100, status=None, timeout=60):
    print(info.id, info.status)
```

Batch operations are also accessible directly from model instances via
`as_batch()`, `batch_run()`, and `batch_run_deferred()` methods (from
`BaseModelBatchMixin`).

---

## Method Availability Summary

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
| Web Search | Yes | No | No | -- | No | No | No |
| Image Search | Yes | No | No | -- | No | No | No |
| By-Image Search | Yes | No | No | -- | No | No | No |
