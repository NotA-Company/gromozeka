# Task-Specific Memories

Archived durable working memory for completed features and subsystems.

Use these files as companions to [`../teamlead-memory.md`](../teamlead-memory.md):

- Keep repo-wide rules, cross-cutting gotchas, and workflow lessons in `teamlead-memory.md`.
- Keep subsystem-scoped discoveries here when they are still useful, but too specific for the main memory file.
- Promote any newly learned repo-wide fact back into `teamlead-memory.md`.
- Never store secrets, tokens, `.env` values, or raw logs.

## Available Files

- [`any-type-cleanup.md`](any-type-cleanup.md) — durable notes for the `Any` type cleanup: patterns established, files changed, genuine patterns preserved.
- [`bot-answer-probability.md`](bot-answer-probability.md) — durable notes for the bot answer probability feature: gating logic, detection heuristic, test coverage.
- [`chat-history-search.md`](chat-history-search.md) — durable notes for the chat history search feature: implementation decisions, anti-patterns learned (20 items), Step 2 gotchas, embedding pipeline, and all review fix rounds.
- [`dedoodization.md`](dedoodization.md) — durable notes for the dedoodization script and repo-wide cleanup of informal language.
- [`delete-from-user.md`](delete-from-user.md) — durable notes for the `DeleteFromUserMessageHandler`: message deletion commands, author extraction gotchas.
- [`max-api-migration.md`](max-api-migration.md) — durable notes for the Max API endpoint migration: `platform-api2`, TLS/SSL, SOCKS5 caveat, polling.
- [`max-webhook-support.md`](max-webhook-support.md) — durable notes for the Max webhook receiver: two-process architecture, deferred processing, post-review fixes.
- [`proxy.md`](proxy.md) — durable notes for `lib/proxy/`, proxy configuration, per-service proxy overrides, HTTP client inventory, and the proxy refactoring anti-patterns.
- [`proxy-lifecycle.md`](proxy-lifecycle.md) — durable notes for the proxy lifecycle management feature: `ProxyService`, `ProxyLifecycle`, subprocess management, health checks, and call-site migration.
- [`resender.md`](resender.md) — durable notes for the Resender module: cron-based message forwarding, media group handling, forward feature.
- [`sandbox.md`](sandbox.md) — durable notes for `lib/sandbox/`, sandbox config, Docker runtime behavior, and sandbox bot integration.
- [`shutdown-state-dump.md`](shutdown-state-dump.md) — durable notes for the shutdown diagnostics: per-chat queue state dump, rate limiter statistics.
- [`test-reorganization.md`](test-reorganization.md) — durable notes for the test layout migration (collocated -> `tests/` mirror), conventions, and post-reorg doc audit.
- [`use-tools-filtering.md`](use-tools-filtering.md) — durable notes for per-tool LLM filtering: `ToolName` StrEnum, `UseToolsType`, execution guard.
- [`user-memories.md`](user-memories.md) — durable notes for the unified per-`(chat, user, thread)` structured memory system (permanent + ephemeral, vec0 search, 3 LLM tools, `_buildMemoriesBlock` injection, regen cron, refinement rewrite). Supersedes the rolling-bio subsystem.
- [`user-memory-refinement.md`](user-memory-refinement.md) — **SUPERSEDED.** Durable notes for the predecessor rolling-bio memory-refinement subsystem (`applyUserMetadata` / `userSummary` / `formatForLLM` summary injection, removed in Phase 4b). Kept as historical context; the accounting/cron/locking/cursor machinery documented there still governs `_runRefinement` and was adapted for the new system.
- [`vector-search.md`](vector-search.md) — durable notes for native vector search: `sqlite-vec` integration, `vec0` tables, dual-write, dimension-aware design.
