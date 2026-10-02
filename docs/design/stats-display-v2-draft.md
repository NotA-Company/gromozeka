---
category: design
---

# Design: Statistics display v2 — owner-facing operational analytics

**Status: DRAFT — goals only, not designed.** Parking-lot document; no decisions beyond
the ratified goal list below. Design work has not started.

## Context

[Statistics display v1](stats-display-v1.md) ships user-scoped stats views: per-chat
(`/stats` in a group) and the user's own private chats. v2 is a different audience and
a different question: **operational analytics for the bot owner** — how the whole bot
is used, which models serve it, where the errors/latency/costs concentrate. It builds
on the v1 read API (`query()` on the `lib/stats` ABC, D4 in v1).

## Goals (user-ratified direction, 2026-08-18)

bot_owner-only ability to get:

- **Global stats** across ALL chats. Note: true cross-label totals require post-query
  SUM over `stat_aggregates` rows — the `__global__` rollup rows are emitted per
  unique label-combo, not as true totals (see [stats-display-v1.md](stats-display-v1.md)
  §2.1), so "global" cannot be read as a single pre-aggregated row per event type.
- **Per-model stats** from `llm_request` events: labels `modelName` / `modelId` /
  `provider` / `generationType` / `status`; metrics `input_tokens` / `output_tokens` /
  `total_tokens` / `request_count` / `is_error` / `elapsed_time`. Answers: usage,
  error rates, latency per model.
- **Per-chat-per-model stats** (cross-tab): which models serve which chats, at what
  volume/token cost.
- **Etc.** — anything else derivable from existing labels with zero collection
  changes, e.g.:
  - per-tool global usage (`llm_tool_call`: `toolName`);
  - per-command global usage (`command`: `commandName`);
  - STT provider stats (`stt_request`: `provider` / `model`);
  - message-volume trends across all chats (`message` events).

## Non-goals (v2)

- Currency cost accounting — tokens only.
- Real-time dashboards.
- Data export.
- New collection events — v2 must reuse the five existing event types
  (`message`, `command`, `llm_request`, `llm_tool_call`, `stt_request`).

## Open questions

- Surface shape: owner-only flag on the existing `/stats` command vs a separate
  owner command?
- Query-load strategy: global views scan many label-combos — need limit/pagination
  or top-N shaping in the analysis layer?
- Does per-chat-per-model need owner chat-membership restrictions? Probably not —
  the owner sees all chats by definition.

## Related

- [stats-display-v1.md](stats-display-v1.md) — the v1 design this builds on.
- [stats-collecting-v1.md](stats-collecting-v1.md) — collection-side contracts.
- [stats-consumerid-gaps.md](stats-consumerid-gaps.md) — per-chat attribution
  gaps in `llm_request` — **fixed 2026-08-23** (see its §Resolution); only
  pre-fix rows remain affected.
