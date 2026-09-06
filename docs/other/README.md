# docs/other/ — third-party API material

Verbatim dumps of third-party API documentation, kept in-tree for offline
consultation. This is vendor material, not Gromozeka documentation; nothing
in this subtree is maintained or updated for drift.

## Access rule

Everything under `docs/other/` — including this README — is **excluded from
markdown-mcp indexing and search** (see the `exclude` list in the repo-root
`.markdown-mcp.toml`). It is reachable only via direct file access or links;
items here never surface in `doc_search` results. This README itself sits
inside the excluded prefix and is therefore unindexed too; it is linked from
[`docs/README.md`](../README.md) (which IS indexed), so a search for e.g.
"yc-ai-sdk" surfaces that entry point, which points here.

## Contents

- [`telegram-markdown-v2.txt`](telegram-markdown-v2.txt) — Telegram Bot API
  MarkdownV2 `parse_mode` syntax reference. Consult when building
  Telegram-facing message text with entities that need careful escaping.

- [`yc-ai-sdk/`](yc-ai-sdk/) — Yandex Cloud AI Studio SDK reference
  (`yandex-ai-studio-sdk` v0.22.0), captured from the installed SDK source
  and systematically re-verified against the pin. Consult when working on
  the Yandex AI providers (`lib/ai/providers/yc_sdk_provider.py`,
  `yc_openai_provider.py`) or upgrading the SDK pin. Files:
  - [`index.md`](yc-ai-sdk/index.md) — bundle entry point: verification
    status, installation, and main SDK entry points; start here.
  - [`completions.md`](yc-ai-sdk/completions.md) — gRPC completions surface
    (the primary LLM text-generation path).
  - [`chat-openai-compat.md`](yc-ai-sdk/chat-openai-compat.md) — the
    OpenAI-compatible chat API surface.
  - [`tools-and-structured-output.md`](yc-ai-sdk/tools-and-structured-output.md) —
    tool/function calling and structured output support.
  - [`image-generation.md`](yc-ai-sdk/image-generation.md) — image
    generation domain.
  - [`speech.md`](yc-ai-sdk/speech.md) — speech synthesis and recognition
    (TTS/STT) domain.
  - [`embeddings-and-other.md`](yc-ai-sdk/embeddings-and-other.md) —
    embeddings and the remaining SDK domains (classifiers, search, tuning,
    datasets, batch).
  - [`gap-analysis.md`](yc-ai-sdk/gap-analysis.md) — which SDK surfaces
    Gromozeka's providers actually use versus what the SDK exposes.

- [`geocode-maps/`](geocode-maps/) — Geocode-Maps HTTP API
  (`geocode.maps.co`), used by the weather feature for address-to-coordinate
  lookups. Consult when touching geocoding behavior or its caching.
  - [`Geocode-Maps-API.md`](geocode-maps/Geocode-Maps-API.md) — endpoint
    reference: forward geocoding (`/search`), reverse geocoding, and
    related endpoints.
  - [`lookup-Angarsk-jsonv2.json`](geocode-maps/lookup-Angarsk-jsonv2.json) —
    captured forward-geocoding (lookup) response sample.
  - [`reverse-Angarsk-jsonv2.json`](geocode-maps/reverse-Angarsk-jsonv2.json) —
    captured reverse-geocoding response sample.
  - [`search-Angarsk-jsonv2.json`](geocode-maps/search-Angarsk-jsonv2.json) —
    captured `/search` endpoint response sample.

- [`Max-Messenger/`](Max-Messenger/) — Max Bot API wire specifications.
  Consult when working on the Max platform adapter (`internal/bot/max/`,
  `lib/max_bot/`) or the webhook receiver (`lib/max_webhook_receiver/`).
  - [`swagger-2025.11.16.json`](Max-Messenger/swagger-2025.11.16.json) —
    OpenAPI 3.0 JSON dump of the Max Bot API (newer capture).
  - [`schema-2025.04.08.yaml`](Max-Messenger/schema-2025.04.08.yaml) —
    OpenAPI 3.0 YAML schema of the Max Bot API (older capture).
