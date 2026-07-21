# Changelog

All notable changes to this project. The changelog is the user-visible record
of what changed and why — not a commit log, and not release notes. For the
process governing this file, see [docs/llm/changelog.md](docs/llm/changelog.md).

## [Unreleased]

### Added
- `/refine-memory` slashcommand for extracting task-specific deep-dive sections from `docs/llm/teamlead-memory.md` into `docs/llm/memories/` to keep the main memory file compact; routed to `teamlead` as a subtask.
- `/review-large` slashcommand for running the large-changes review methodology from `docs/llm/reviewing-large-changes.md` on a diff (>24 files): characterize, batch by feature domain, parallel per-batch review, integration pass, consolidated findings — stops before remediation; routed to `teamlead`.
- `input_image_format` per-model config key — declares the supported **input** (vision) image MIME formats; input images whose detected MIME is not in the list are auto-converted to the first listed format (e.g. webp→jpeg) before being sent to the model. Unset/empty = accept any format. OpenAI-compatible providers only; conversion failures (corrupt/unsupported/oversized images, including a decompression-bomb pixel cap) degrade gracefully by sending the original. Motivating case: YC `yc/qwen3.6-35b-a3b` (the image-parsing fallback) now declares `input_image_format = ["image/jpeg", "image/png"]` so webp Telegram stickers no longer get rejected.
- New `tests/dependencies/` suite of dependency-usage regression tests pinning the current behavior of pinned third-party libraries (python-dateutil, tomli, python-magic, html-to-markdown, sqlite-vec) so a version bump that changes behavior fails loudly. Each test asserts its pinned library version via `importlib.metadata.version()` (sqlite-vec via `SELECT vec_version()`). (The original suite also covered `numpy` via `test_numpy.py`; that file was deleted when the chat-search numpy cosine path was removed — see the `Removed` entry below.)
- `search_messages` LLM tool gained a `current_thread_only` parameter (default true) that restricted results to the current thread/topic; an explicit `thread_message_id` overrode it.
- `search_messages` LLM tool gained a `substring` parameter for case-insensitive exact-text filtering; substring-only searches (no `query`) skipped embedding generation and worked in chats without embeddings enabled.
- `web_search` and `get_url_content` LLM tools gained an optional `condensing_prompt` parameter that overrides the default document-condensing prompt per call when fetched page content exceeds `max_size`; empty/whitespace-only falls back to the per-chat `DOCUMENT_CONDENSING_PROMPT` default. `web_search` also gained a `max_size` parameter (forwarded per-page to `get_url_content`, closing a pre-existing gap where every batch page silently used the default `10240`).

### Changed
- `migration_025_embedding_model_lookup` normalised embedding provenance into a new `models` lookup table (keyed by an app-generated `model_id` integer with `UNIQUE(model, dimensions)`). `chat_messages` and `user_memories` now carry `model_id` instead of the legacy per-row `(model, dimensions)` / `(embedding_model, embedding_dimensions)` pairs; vec0 tables (`vec_message_embeddings_{N}`, `vec_user_memories_{N}`) are recreated lazily with `model_id INTEGER PARTITION KEY` (was `model TEXT`). The migration drops the `message_embeddings` BLOB side table and its `idx_message_embeddings_chat_model` index. **Vec0 tables are dropped and lazily recreated on the next embed call; semantic search is temporarily degraded until the backfill cron catches up (same pattern as a model switch today). DB backup strongly recommended before running the migration.** `down()` is schema-correct but honestly lossy for vectors (the dropped BLOBs cannot be regenerated from `model_id` alone; vec0 tables are not re-created by `down()`).
- Chat-history semantic search is now vec0-only — the in-process numpy cosine fallback (`ChatSearchRepository._loadEmbeddingsFromDb` + inline matrix math) was removed; `searchChatMessages` returns the empty list when vec0 is unavailable instead of falling back to a Python-side scan.
- Chat-message embedding storage is now `chat_messages.model_id` + vec0 only (single write per embed); the previous dual-write to `message_embeddings` (BLOB) + vec0 is retired alongside the BLOB table.

### Removed
- `numpy` direct dependency (was `numpy==2.5.1` in `requirements.direct.txt`); it remains pinned in `requirements.txt` as an unresolved transitive of `fastembed`. The chat-search cosine-similarity code path that needed it is gone, and `lib/ai/providers/fastembed_provider.py` had its runtime `import numpy as np` reduced to a `TYPE_CHECKING`-only annotation import (no behaviour change — the file never called numpy directly, the import only carried the `embedOne` return-type annotation). `tests/dependencies/test_numpy.py` was deleted alongside (21 tests removed).
- `message_embeddings` table and the `MessageEmbeddingDict` TypedDict (backing table dropped by `migration_025`); `ChatEmbeddingsRepository.getMessageEmbedding` and `ChatEmbeddingsRepository.deleteChatEmbeddings` (no production callers — tests only).

### Changed
- Broken-tool-call retries preserve the original bracket text in `resultText` for model context and suppress intermediate retry prose from being sent to the user.
- `search_messages`, `list_users`, and `get_thread` LLM tools no longer re-check the `ALLOW_TOOLS_COMMANDS` chat setting inside the tool handler; LLM tools are now gated solely by `USE_TOOLS` at chat time, while `ALLOW_TOOLS_COMMANDS` gates only slash commands of `CommandCategory.TOOLS`. (With `USE_TOOLS=true` + `ALLOW_TOOLS_COMMANDS=false`, the LLM can now call these tools.)
- `LLMService.generateTextViaLLM` now bounds the tool-calling loop by default (`maxRounds=DEFAULT_MAX_ROUNDS`=32, in `internal/services/llm/constants.py`); once the budget is exhausted it drops tool schemas, clears the tool execution allowlist, disables tool-call healing, injects a steering directive, forces the loop to terminate within one additional round, sets `ModelRunResult.roundLimitHit=True`, and logs a service-level warning. A fallback answer is synthesized only for an empty `FINAL` or a post-budget `TOOL_CALLS` (a glitching model that ignored the empty tools); genuine error statuses (`ERROR`/`CONTENT_FILTER`/`UNKNOWN`) propagate untouched so callers can detect the failure. Pass `maxRounds=None` for unlimited rounds (legacy behavior).
- The memory-refinement loop now detects a `roundLimitHit` result and logs a warning that curation may be incomplete for the batch (previously the cap fired silently and incomplete curation looked like success).
- `lib/ai` model/provider `temperature` constructor argument replaced with `customParams: Optional[Dict[str, Any]]` on `AbstractModel` (and propagated through `addModel`/`_createModelInstance`); the `_getImageRequestOptions` whitelist was removed and Fastembed's `_CONSUMED_EXTRA_KEYS` filter replaced with direct `**customParams` passthrough. Per-model TOML config now nests inference params under `customParams.*`.

### Fixed
- LLM tool-call healing now detects `<tool_call>{…}</tool_call>` tag-wrapped JSON calls (emitted by e.g. YC aliceai-llm) and converts them into real tool calls instead of leaking the raw tags to the user.
- LLM tool-call healing now scans every ``[...]`` block in the response (not just the first) and accepts mid-message brackets when followed by a fenced JSON params block, so a markdown link earlier in the response no longer shadows the actual broken-call bracket.
- JSON tool-call healing now also accepts `"function"` key as a tool-name source (fallback when `"name"` is absent or empty), so models that emit `{"function": "tool_name", "arguments": {...}}` are healed correctly.

## Initial State - 2026-07-15

### Added
- Multi-platform bot supported both Telegram and Max Messenger behind a unified handler interface.
- LLM-powered chat provided automatic provider fallback across OpenRouter, Yandex Cloud, OpenAI, and custom endpoints.
- AI tool calling (function calling) extended text generation with callable tools.
- Image generation and image/sticker analysis were available.
- User memory system stored structured per-chat memories with semantic vector search, managed by the LLM through add/delete/search tools.
- Chat history search was backed by vector embeddings and exposed via `/search`.
- Sandboxed Python code execution ran in Docker, exposed via `/run`.
- ML-powered spam detection used a Naive Bayes classifier trainable through `/learn_spam` and `/learn_ham`.
- Divination delivered tarot and runes readings with LLM-driven layout discovery via `/taro` and `/runes`.
- Real-time weather forecasts via OpenWeatherMap (with geocoding) and Yandex web search were served with caching.
- Sliding-window rate limiting was provided.
- Local filesystem or S3-compatible file storage was provided.
- Hierarchical TOML configuration with layered `--config-dir` overrides was provided.
