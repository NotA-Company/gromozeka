# Design Archive

> **Status:** Historical design documents and ADRs
> **Warning:** May contain stale file paths or superseded architectures

---

## Overview

This directory contains **historical design documents** and Architecture Decision Records (ADRs) from various phases of the project. These documents capture the design reasoning and historical context but may not reflect the current implementation.

## File Status Summary

| File | Status | Notes |
|------|--------|-------|
| [`rate-limiter-library-design-v0.md`](rate-limiter-library-design-v0.md) | 🔴 Historical | Early rate limiter design — for context only; see [`docs/llm/services.md`](../../llm/services.md) for current implementation details |
| [`cache-service-design-v0.md`](cache-service-design-v0.md) | 🔴 Historical | Initial cache service design — architecture has evolved significantly |
| [`command-handler-decorator-v0.md`](command-handler-decorator-v0.md) | 🔴 Historical | v0 of handler decorator system — current decorator design is in [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) |
| [`command-handler-decorator-v1.md`](command-handler-decorator-v1.md) | 🟡 Partially Historical | v1 design — some concepts may still apply; current best practice is to read the handler examples in [`internal/bot/common/handlers/`](../../internal/bot/common/handlers/) |
| [`bot-handlers-refactoring-v1.md`](bot-handlers-refactoring-v1.md) | 🔴 Historical | Historical refactoring plan — handler architecture has since evolved |
| [`geocode-maps-client-design-v0.md`](geocode-maps-client-design-v0.md) | 🟡 Reference-able | Implementation likely followed this design; verify against [`lib/geocode_maps/`](../../../lib/geocode_maps/) for actual current implementation |
| [`golden-data-testing-system-v0.md`](golden-data-testing-system-v0.md) | 🔴 Historical | Early golden-data testing design — see [`docs/llm/testing.md`](../../llm/testing.md) for current testing guidance |
| [`golden-data-testing-system-v1.md`](golden-data-testing-system-v1.md) | 🟡 Partially Historical | v1 design — may partially reflect current golden testing setup in [`tests/lib_ai/golden/`](../../../tests/lib_ai/golden/) |

## Common Staleness Patterns

### 1. Database-Related References
Many archive design docs may reference the old `DatabaseWrapper` pattern or file structures that no longer exist:
- `internal/database/wrapper.py` ← **DELETED** (replaced by `Database` façade + repositories)
- Repository pattern in `internal/database/repositories/` is current architecture
- See [`docs/llm/database.md`](../../llm/database.md) for current database architecture

### 2. Handler Path References
Design docs may reference handler locations that have been reorganized:
- Current handlers: `internal/bot/common/handlers/`
- Platform adapters: `internal/bot/telegram/`, `internal/bot/max/`
- Handler base: `internal/bot/common/handlers/base.py`

### 3. Service Layer References
Service architecture references should be verified against:
- [`docs/llm/services.md`](../../llm/services.md) — canonical services guide
- `internal/services/` — actual service implementations

## Using This Archive

### For Historical Context
✅ Read when you want to understand:
- Why an architectural decision was made
- What alternatives were considered
- The evolution of a component over time
- Context for old bug reports or discussions

### For Implementation Reference
❌ Do NOT use as current implementation guidance. Before code changes:
1. Verify file/directory paths exist
2. Check current code structure
3. Cross-reference with active_docs in [`docs/llm/`](../../llm/)
4. Run `./venv/bin/python3 main.py --print-config` to see actual config structure

### For Design Inspiration
✅ Design patterns and architectural concepts may still be valuable, but implementation details may have changed. Consider:
- Has the problem been solved differently?
- Are naming conventions consistent with current style?
- Do the patterns fit the current architecture?

## Active Documentation for Design Decisions

For current architecture, design patterns, and ADRs:

| Topic | Current Doc |
|-------|-------------|
| Overall architecture | [`docs/llm/architecture.md`](../../llm/architecture.md) |
| Handler system design | [`docs/llm/handlers.md`](../../llm/handlers.md) |
| Database architecture | [`docs/llm/database.md`](../../llm/database.md) |
| Service layer design | [`docs/llm/services.md`](../../llm/services.md) |
| Configuration design | [`docs/llm/configuration.md`](../../llm/configuration.md) |
| Libraries design | [`docs/llm/libraries.md`](../../llm/libraries.md) |
| SQL portability decisions | [`docs/sql-portability-guide.md`](../../sql-portability-guide.md) |

---

*Last updated: 2026-05-08*
*Design archive maintained for historical context only*
