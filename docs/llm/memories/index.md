---
category: reference
description: Index of task-specific agent memory files — searchable via doc_search(query, file_glob="llm/memories/*.md") or read the relevant one before working on a subsystem.
---

# Task-Specific Memories

Archived durable working memory for completed features and subsystems.

Use these files as companions to [`../teamlead-memory.md`](../teamlead-memory.md):

- Keep repo-wide rules, cross-cutting gotchas, and workflow lessons in `teamlead-memory.md`.
- Keep subsystem-scoped discoveries here when they are still useful, but too specific for the main memory file.
- Promote any newly learned repo-wide fact back into `teamlead-memory.md`.
- Never store secrets, tokens, `.env` values, or raw logs.
- Files retired from this index are archived under [`../../archive/llm-memories/`](../../archive/llm-memories/README.md) (excluded from the markdown-mcp index/search; see its README for reasons and dates).

## Available Files

- [`bot-answer-probability.md`](bot-answer-probability.md) — durable notes for the bot answer probability feature: gating logic, detection heuristic, test coverage.
- [`chat-accessibility.md`](chat-accessibility.md) — bot-kicked-from-chat handling: `getChatAdmins` graceful degradation (Forbidden/NotFoundError → `{}` + warning, no cache poisoning) + `chat_info.bot_status` tracking (migration_026, `ChatBotStatus`, cache-aside, preprocessor self-heal).
- [`chat-history-search.md`](chat-history-search.md) — durable notes for the chat history search feature: implementation decisions, anti-patterns learned (20 items), Step 2 gotchas, embedding pipeline, and all review fix rounds.
- [`chat-settings-pages.md`](chat-settings-pages.md) — `ChatSettingsPage` system invariants: tier-monotonic declaration order, ephemeral page ints, two-tier (page + model-tier) access gating — lowering a STRING/BOOL/INT/FLOAT setting's page = direct privilege escalation, `LLM_BASE` retirement, test/doc sync surfaces for page reassignment.
- [`chat-users-cache.md`](chat-users-cache.md) — ADR-015 write-through `chat_users` cache in `CacheService`: `_chatUsersMetadataLock`, `messages_count` staleness hazard.
- [`condensed-context-retrieval.md`](condensed-context-retrieval.md) — ADR-019 context-condensing subsystem: `condenseContext` primitive, three pathways (A/B/C), `CondensingDict`/`renderCondensedSummary`, `get_messages_by_ids` LLM tool.
- [`db-cache-cleanup.md`](db-cache-cleanup.md) — Durable notes for the DB cache cleanup mechanism: `GenericDatabaseCache.clearOld` instance sweeps, weekly cron + on-shutdown triggers, per-namespace TTLs, Bayes tokens cleanup, `cache_storage` exemption.
- [`db-maintenance-scripts.md`](db-maintenance-scripts.md) — Standalone `/scripts/` DB-maintenance conventions: direct `sqlite3.connect` precedent, `dest="dryRun"`, `StrEnum` over literals, JSON serializer for `chat_users.metadata`.
- [`delete-from-user.md`](delete-from-user.md) — durable notes for the `DeleteFromUserMessageHandler`: message deletion commands, author extraction gotchas.

### Audits, doc campaigns, and migrations

- [`dependency-usage-tests.md`](dependency-usage-tests.md) — Durable notes for the `tests/dependencies/` dep-usage regression test suite: PURE/EXTERNAL/MIXED/DEV classification, version-pinning convention, behavioral findings (dateutil, html-to-markdown, numpy, sqlite-vec).
- [`doc-link-fix-campaign.md`](doc-link-fix-campaign.md) — `make check-docs` link checker + 376-broken-link fix campaign; leading-slash link convention, exclusion prefixes, depth gotchas.
- [`documentation-audit.md`](documentation-audit.md) — Durable notes from the 2026-06-28 documentation audit: drift-pattern taxonomy, highest/medium/low-drift doc lists, common drift failure modes.
- [`docs-reorg-lessons.md`](docs-reorg-lessons.md) — Durable lessons from the 2026-07-04 docs bulk-reorg: sibling-relative-link gap inside moved files, code-doc references to moved docs in `*.py` docstrings / migration modules + `tests/**` golden-doc files (hotspots `internal/**/*.py` + `tests/**`; `lib/` is clean), config-comment doc-path references.
- [`docs-rewrite-2026-09.md`](docs-rewrite-2026-09.md) — docs rewrite arc (2026-09-06, COMPLETE): owner decisions, playbook-driven 7-phase ledger (`adb1927c`…`7ab3c64f`) + follow-up round (`b0ae0bab`/`da724bcc`/`9c5bf91e`), residual ambiguities. Companions: [`docs-reorg-lessons.md`](docs-reorg-lessons.md), [`full-docs-audit.md`](full-docs-audit.md).
- [`embedding-model-lookup-refactor.md`](embedding-model-lookup-refactor.md) — Durable notes for the embedding model-lookup refactor: migration_025, `EmbeddingModelsRepository`, vec0 partition key, D7 INTEGER PK, Gate 1+2 reviews, git-stash disaster recovery, dataSource plumbing, numpy removal.
- [`full-docs-audit.md`](full-docs-audit.md) — Durable notes from the 2026-07-18 85-file full `/docs` audit: ~78 fixes, 13 archives, 5-phase process, ~30 YC SDK drifts, 19 recurring drift patterns, archive-vs-live decision principle.
- [`httpx2-migration.md`](httpx2-migration.md) — httpx→httpx2 research + completed migration (2026-08-13): `alias_httpx()`, PTB b2 decision, native SOCKS `proxy=`, lockfile facts, h2-over-SOCKS5 verdict (D3 guard removed as dead weight).

### LLM subsystem and review-campaign memories

- [`llm-customparams-refactor.md`](llm-customparams-refactor.md) — Durable notes for the 2026-07-20 LLM `customParams` refactor in `lib/ai`: architecture (5 provider + 5 model classes), per-request param flow, TOML shape, test patterns.
- [`llm-empty-truncated-final.md`](llm-empty-truncated-final.md) — Empty `TRUNCATED_FINAL` production bug (Qwen3 budget exhaustion → empty content → `BadRequest`): Item 1 observability dump + handler-level `SKIPPED_BY_MODEL` silent-drop mitigation shipped; Option A provider downgrade, `bot.py` empty-string guard, and regression tests still pending.
- [`llm-max-rounds.md`](llm-max-rounds.md) — Durable notes for the `LLMService.generateTextViaLLM(maxRounds=...)` budget/round-limit feature: `budgetExhausted` gates, `roundLimitHit` flag, steering fold-in, layering of `internal/services/llm/constants.py`.
- [`llm-messages-handler.md`](llm-messages-handler.md) — Durable anchors for `internal/bot/common/handlers/llm_messages.py` (`_sendLLMChatMessage`, `handleReply`/`handleMention`/`handleRandomMessage`, abstention sentinel, `<media-description>` extraction, chat-settings symbol locations).
- [`llm-tool-call-healing.md`](llm-tool-call-healing.md) — Durable notes for the LLM tool-call healing subsystem (`_tryHealToolCall` orchestrator + 6 matchers, broken-known-tool fallback, `LLMToolCall.errorMessage` consumer-audit gotcha).
- [`llm-user-message-format.md`](llm-user-message-format.md) — Durable notes for the LLM user-message JSON format: `EnsuredMessage.formatForLLM` JSON branch, `chat-prompt-suffix` enumeration, ADR-018/019 render entry points.
- [`review-fix-lessons.md`](review-fix-lessons.md) — Durable lessons from the 2026-07-01 review-fix round on branch `max-v2`: single-developer many-fix dispatch, `logger.exception` misuse pattern, `except Exception` narrowing, config-defaults alignment.

### Platform and infrastructure memories

- [`lib-db-extraction.md`](lib-db-extraction.md) — lib/db extraction arc (ADR-022): providers + DatabaseManager + utils moves, Protocol `.asStr()` cut, DatabaseStatsStorage → lib/stats, lib/cache extraction (ADR-024, `clearOld` on CacheInterface), SQLinkProvider test suite; `git mv` nesting catch, census/anchor lessons.
- [`max-api-migration.md`](max-api-migration.md) — durable notes for the Max API endpoint migration: `platform-api2`, TLS/SSL, SOCKS5 caveat, polling.
- [`max-webhook-receiver-extraction.md`](max-webhook-receiver-extraction.md) — receiver → lib arc (ADR-025): ratification + design rounds, own-DB amendment (migration_029), commit-per-step series B→G, Docker artifacts + httpx2-alias rework, setup-docs live audit, scripts alias-crash fix, receiver runtime-closure facts.
- [`memories-context-dedup.md`](memories-context-dedup.md) — ADR-018 lazy render-time memory resolution + per-context newest→oldest dedup; companion to `user-memories.md` §"Render-time resolution".
- [`proxy.md`](proxy.md) — durable notes for `lib/proxy/`, proxy configuration, per-service proxy overrides, HTTP client inventory, and the proxy refactoring anti-patterns.
- [`proxy-lifecycle.md`](proxy-lifecycle.md) — durable notes for the proxy lifecycle management feature: `ProxyService`, `ProxyLifecycle`, subprocess management, health checks, and call-site migration.

### Handlers and runtime subsystems

- [`resender.md`](resender.md) — durable notes for the Resender module: cron-based message forwarding, media group handling, forward feature.
- [`sandbox.md`](sandbox.md) — durable notes for `lib/sandbox/`, sandbox config, Docker runtime behavior, and sandbox bot integration.
- [`sandbox-update.md`](sandbox-update.md) — `/sandbox update` arc (2026-09-04 → 2026-09-06, COMPLETE): spike-verified pip `--target` behavior, rev-2 staged-install + atomic pool swap (pip never writes the live pool), StagingRun simplification round, real-Docker test hardening, ResourceWarnings→error policy. Companion to [`sandbox.md`](sandbox.md).
- [`shutdown-state-dump.md`](shutdown-state-dump.md) — durable notes for the shutdown diagnostics: per-chat queue state dump, rate limiter statistics.
- [`skills-agents-audit.md`](skills-agents-audit.md) — Durable notes from the 2026-07-11 skills/agents landscape audit: inventory (8 project skills, 4 global, 7 agents), identified gaps, session outcomes (getChatSettings drift resolution, code-reviewer/docs-writer permission hardening, `make check-docs` shipped).
- [`stats-subsystem.md`](stats-subsystem.md) — the lib/stats arc: subsystem map, stats-collecting-v1 (message/llm_tool_call/command events, migration_027), StatsAggregationService (fail-fast config, delayed-task trigger, retention), stats-display v1 (`/stats` command, argparse-like grammar, fenced Top blocks, web tier + `[stats.pages]`), U11/U12/user-amend rounds, whole-branch review + reversal campaigns, getBotId/botUsername TTL caches.
- [`stt-media-transcription.md`](stt-media-transcription.md) — STT media-transcription arc: lib/stt design + implementation + user simplifications, stateless STTService, `_processMediaV2` handler integration, v1.1 Object Storage + provider stats, speaker attribution/channelTag closeout, aurumentation golden suite, v1+v1.1 review campaign.
- [`telegram-send-retry.md`](telegram-send-retry.md) — `TheBot._retryTelegramSend` (PTB TimedOut/NetworkError/RetryAfter ordering, 3 attempts, narrowed-except markdown-fallback restructure, idempotency stance) + PTBDeprecationWarning test-warnings triage (32 → 0).

### Tests, tools, and vector search

- [`test-suite-speedup.md`](test-suite-speedup.md) — Durable notes from the 2026-07-12 test-suite speedup effort (107s→38.17s, −64.3%): performance profile, fake-clock + no-op asyncio.sleep patterns, unittest/pytest fixture interaction gotchas, flagged-but-not-fixed items.
- [`use-tools-filtering.md`](use-tools-filtering.md) — durable notes for per-tool LLM filtering: `ToolName` StrEnum, `UseToolsType`, execution guard.
- [`user-memories.md`](user-memories.md) — durable notes for the unified per-`(chat, user, thread)` structured memory system (permanent + ephemeral, vec0 search, 3 LLM tools, centralised arrival-time injection via `MessagePreprocessorHandler.injectMemories`, regen cron, refinement rewrite). Supersedes the rolling-bio subsystem.
- [`user-memory-refinement.md`](user-memory-refinement.md) — **SUPERSEDED.** Durable notes for the predecessor rolling-bio memory-refinement subsystem (`applyUserMetadata` / `userSummary` / `formatForLLM` summary injection, removed in Phase 4b). Kept as historical context; the accounting/cron/locking/cursor machinery documented there still governs `_runRefinement` and was adapted for the new system.
- [`user-memory-v2-review.md`](user-memory-v2-review.md) — Durable notes from the 2026-07-14 `user-memory-v2` pre-merge review campaign (140 files / 28 commits): pre-review batching plan + post-review durable contracts/invariants (`CondensingDict.messageCount`, per-message memory injection, `getThreadByMessageForLLM` dedup, `condenseContext.batchLength` floor, `MAX_SQL_VARIABLES=900`).
- [`vector-search.md`](vector-search.md) — durable notes for native vector search: `sqlite-vec` integration, `vec0` tables, dual-write, dimension-aware design.
