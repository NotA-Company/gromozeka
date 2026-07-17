# Changelog

All notable changes to this project. The changelog is the user-visible record
of what changed and why — not a commit log, and not release notes. For the
process governing this file, see [docs/llm/changelog.md](docs/llm/changelog.md).

## [Unreleased]

### Added
- `input_image_format` per-model config key — declares the supported **input** (vision) image MIME formats; input images whose detected MIME is not in the list are auto-converted to the first listed format (e.g. webp→jpeg) before being sent to the model. Unset/empty = accept any format. OpenAI-compatible providers only; conversion failures (corrupt/unsupported/oversized images, including a decompression-bomb pixel cap) degrade gracefully by sending the original. Motivating case: YC `yc/qwen3.6-35b-a3b` (the image-parsing fallback) now declares `input_image_format = ["image/jpeg", "image/png"]` so webp Telegram stickers no longer get rejected.
- New `tests/dependencies/` suite of dependency-usage regression tests (79 tests) pinning the current behavior of pinned third-party libraries (python-dateutil, tomli, python-magic, html-to-markdown, numpy, sqlite-vec) so a version bump that changes behavior fails loudly. Each test asserts its pinned library version via `importlib.metadata.version()` (sqlite-vec via `SELECT vec_version()`).
- `search_messages` LLM tool gained a `current_thread_only` parameter (default true) that restricted results to the current thread/topic; an explicit `thread_message_id` overrode it.
- `search_messages` LLM tool gained a `substring` parameter for case-insensitive exact-text filtering; substring-only searches (no `query`) skipped embedding generation and worked in chats without embeddings enabled.
- `web_search` and `get_url_content` LLM tools gained an optional `condensing_prompt` parameter that overrides the default document-condensing prompt per call when fetched page content exceeds `max_size`; empty/whitespace-only falls back to the per-chat `DOCUMENT_CONDENSING_PROMPT` default. `web_search` also gained a `max_size` parameter (forwarded per-page to `get_url_content`, closing a pre-existing gap where every batch page silently used the default `10240`).

### Changed
- `search_messages`, `list_users`, and `get_thread` LLM tools no longer re-check the `ALLOW_TOOLS_COMMANDS` chat setting inside the tool handler; LLM tools are now gated solely by `USE_TOOLS` at chat time, while `ALLOW_TOOLS_COMMANDS` gates only slash commands of `CommandCategory.TOOLS`. (With `USE_TOOLS=true` + `ALLOW_TOOLS_COMMANDS=false`, the LLM can now call these tools.)
- `LLMService.generateTextViaLLM` now bounds the tool-calling loop by default (`maxRounds=DEFAULT_MAX_ROUNDS`=32, in `internal/services/llm/constants.py`); once the budget is exhausted it drops tool schemas, clears the tool execution allowlist, disables tool-call healing, injects a steering directive, forces the loop to terminate within one additional round, sets `ModelRunResult.roundLimitHit=True`, and logs a service-level warning. A fallback answer is synthesized only for an empty `FINAL` or a post-budget `TOOL_CALLS` (a glitching model that ignored the empty tools); genuine error statuses (`ERROR`/`CONTENT_FILTER`/`UNKNOWN`) propagate untouched so callers can detect the failure. Pass `maxRounds=None` for unlimited rounds (legacy behavior).
- The memory-refinement loop now detects a `roundLimitHit` result and logs a warning that curation may be incomplete for the batch (previously the cap fired silently and incomplete curation looked like success).

### Fixed
- LLM tool-call healing now detects `<tool_call>{…}</tool_call>` tag-wrapped JSON calls (emitted by e.g. YC aliceai-llm) and converts them into real tool calls instead of leaking the raw tags to the user.
- LLM tool-call healing now returns a retry-error to the model for unparseable calls that nonetheless reference a known registered tool, instead of leaking the broken pseudo-call text to the user.

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
