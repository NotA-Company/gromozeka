---
category: reference
---

> **Archived 2026-09-06** — superseded agent memory file, moved from `docs/llm/memories/`. Excluded from the markdown-mcp index/search; see [README.md](README.md) for the per-file index.

# Test Reorganization Task Memory

Durable task-specific memory for the completed test reorganization work (2026-05-21).

How to use this file:
- Read it when moving tests, changing test layout conventions, or debugging test discovery issues.
- Keep only test-layout-scoped discoveries here; move repo-wide lessons back to [`../../llm/teamlead-memory.md`](../../llm/teamlead-memory.md).
- Never store secrets, tokens, `.env` values, or raw logs.

## Summary

- **Status:** COMPLETED. ~74 test files moved from collocated locations into `tests/` with source-structure mirroring. Final: **2342 passed, 11 skipped** (skipped = Docker sandbox tests without daemon).
- **Plan document:** [`docs/archive/plans/test-reorganization.md`](../../../docs/archive/plans/test-reorganization.md) — full mapping tables, phases, risks.

## Conventions Established

- `internal/X/Y.py` -> `tests/X/test_Y.py` (strip `internal/` prefix).
- `lib/X/Y.py` -> `tests/lib/X/test_Y.py` (full `tests/lib/` prefix).
- Cross-cutting tests stay at `tests/integration/`, `tests/verification/`.
- `testpaths` stays `["tests", "lib", "internal"]` (lib/ and internal/ now have no test files; harmless).
- Non-test artifacts that originally stayed under `lib/markdown/test/` (`run_tests.sh`, `README.md`, `MarkdownV2_demo.py`) were dropped the same day as the reorg in commit `075e4d5` (2026-05-21, "Drop some obsoleted lib/markdown files"); the `lib/markdown/test/` directory no longer exists. All markdown tests now live under `tests/lib/markdown/`.

## Cleanup

- Old directories removed: `tests/lib_ai/`, `tests/lib_utils/`, `tests/lib_ratelimiter/`, `tests/divination/`, `tests/geocode_maps/`, `tests/openweathermap/`, `tests/yandex_search/`.
- **New rule** (added to `docs/llm/testing.md`, `AGENTS.md`, `docs/llm/index.md`, `docs/llm/tasks.md`): all new tests MUST use mirror layout under `tests/`. No new collocated tests in `lib/` or `internal/`.

## Post-Reorg Doc Audit

- `docs/llm/` and `AGENTS.md` are clean.
- Fixed stale paths in `docs/plans/` (10 files), `docs/design/` (1 file), `docs/templates/` (1 file), `docs/suggestions/` (1 file), `.agents/skills/` (1 file), `internal/database/migrations/README.md`.
- Left `docs/archive/` untouched (historical records).
