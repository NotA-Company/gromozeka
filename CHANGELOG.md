# Changelog

All notable changes to this project. The changelog is the user-visible record
of what changed and why — not a commit log, and not release notes. For the
process governing this file, see [docs/llm/changelog.md](docs/llm/changelog.md).

## [Unreleased]

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
