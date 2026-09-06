# Archived LLM Agent Memory Files

Superseded task-specific agent memory files relocated from `docs/llm/memories/` on 2026-09-06.
This directory is excluded from the markdown-mcp index/search (`.markdown-mcp.toml` `[docs].exclude`)
and from `make check-docs`; files are frozen history — paths and counts inside them are not maintained.

- [any-type-cleanup.md](any-type-cleanup.md) — 2026-06-28 `Any`-type cleanup campaign record; the standing rule lives in `docs/llm/index.md` §3.3, so only the campaign history is kept here.
- [dedoodization.md](dedoodization.md) — 2026-07-02 repo-wide "dood" removal pass; script kept at `scripts/dedoodize.py`, arc closed.
- [large-review-campaign.md](large-review-campaign.md) — 2026-06-28 78-file/6-batch review-campaign lessons; the living methodology is `docs/llm/reviewing-large-changes.md`.
- [max-webhook-support.md](max-webhook-support.md) — pre-ADR-025 webhook-receiver notes; superseded by ADR-013/ADR-025 in `docs/llm/architecture.md` and the operational `docs/max-webhook-setup.md`.
- [test-reorganization.md](test-reorganization.md) — 2026-05-21 collocated→`tests/` test-layout migration; conventions are now normative in `AGENTS.md` and `docs/llm/testing.md`.
