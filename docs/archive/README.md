# Archive Directory

> **Status:** Historical documentation only — not active guidance
> **Purpose:** Records of past design discussions, implementation plans, reports, and proposals

---

## Overview

This directory contains **historical documentation** that has been archived for reference but does **not** represent current active plans or guidance. Files here may contain:

- **Stale file paths** (e.g., references to `internal/database/wrapper.py` which no longer exists)
- **Superseded architecture** (e.g., DatabaseWrapper → Database + repositories pattern)
- **Outdated implementation status** (marked as "not implemented" features that are now complete)
- **Early proposals** that evolved or were abandoned

## ⚠️ Navigation Warnings - Read Before Referencing

When reading archived files, be aware of these known architectural changes:

### Database Layer Migration (completed ~2026-05-02)
- **Old path:** `internal/database/wrapper.py` (3,000+ line monolith) — **DELETED**
- **New pattern:** `internal/database/database.py` (Database façade) + `internal/database/repositories/` (11 domain repositories) + `internal/database/providers/` (sql abstraction)
- Many archive docs reference `DatabaseWrapper` — see current code instead

### Handler Architecture
- Archive reports in `reports/` reference historical handler paths that may have moved
- Current handlers live under `internal/bot/common/handlers/`
- For actual handler guidance, see [`docs/llm/handlers.md`](../../llm/handlers.md)

### Configuration
- Archive docs may reference obsolete config keys or TOML structures
- Current configuration is documented in [`docs/llm/configuration.md`](../../llm/configuration.md)
- See `configs/00-defaults/` for actual shipped defaults

## Directory Structure

```
archive/
├── design/          # Historical design docs and ADRs
├── plans/           # Implementation plans (some superseded)
├── reports/         # Phase reports and analysis (40+ historical reports)
└── README.md        # This file
```

### Subdirectories

#### `design/`
Contains design documents, ADRs (Architecture Decision Records), and early architectural explorations. See [`design/README.md`](design/README.md) for specific file status notes.

#### `plans/`
Implementation plans for features. Some were completed (e.g., divination handler), some were superseded by architectural changes (e.g., DatabaseWrapper cleanup), some remain aspirational.

**Status verification:** Before implementing from an archived plan:
1. Check if the feature already exists (run `grep -r "class Handler" internal/bot/common/handlers/`)
2. Verify file paths match current codebase
3. Cross-reference with active docs in [`docs/llm/`](../../llm/)

#### `reports/`
Historical reports documenting implementation phases, testing results, and analysis. These are kept for audit trail but may reference old architecture or describe resolved issues.

**Notable historical reports:**
- Multi-source database implementation reports (phase 1-6)
- Migration cursor refactoring reports
- Database wrapper TODO fix reports (now superseded by repository pattern)
- Testing implementation reports (various phases)

## When to Use This Directory

### ✅ Appropriate Uses
- **Audit trail:** Understanding how a decision was reached or what was attempted
- **Bug archaeology:** Investigating historical issues or rationale
- **Feature history:** Researching the evolution of a component
- **Learning:** Reading design discussions and trade-off considerations

### ❌ Inappropriate Uses
- **As implementation guidance:** Always verify against current code and active docs
- **For code structure:** File paths may be stale — check the actual codebase
- **For current best practices:** See [`AGENTS.md`](../../AGENTS.md) and [`docs/llm/`](../../llm/)

## Current Active Documentation

For authoritative, up-to-date guidance, use these sources:

| Need | Document | Location |
|------|----------|----------|
| Project rules & hard rules | AGENTS.md | `/AGENTS.md` (repo root) |
| Architecture overview | Architecture guide | [`docs/llm/architecture.md`](../../llm/architecture.md) |
| Handler system | Handler guide | [`docs/llm/handlers.md`](../../llm/handlers.md) |
| Database layer | Database guide | [`docs/llm/database.md`](../../llm/database.md) |
| Services layer | Services guide | [`docs/llm/services.md`](../../llm/services.md) |
| Configuration | Configuration guide | [`docs/llm/configuration.md`](../../llm/configuration.md) |
| Schema reference | Database schemas | [`docs/database-schema.md`](../../database-schema.md), [`docs/database-schema-llm.md`](../../database-schema-llm.md) |
| Active suggestions | Current improvement/refactoring/simplification lists | [`docs/suggestions/`](../suggestions/) |

## Archiving Criteria

Files are moved to `archive/` when they meet **one or more** of these criteria:

1. **Feature completed** and the plan/history is no longer needed for active work
2. **Architecture changed** substantially (file paths, patterns, or structures superseded)
3. **Proposal abandoned** or significantly revised
4. **Historical report** documenting a completed phase or resolved issue
5. **Status stale** for extended period without updates

## Link Updates

If you find a broken link from an active doc pointing into `archive/`, update the reference to point to current documentation instead. Archive files are **not updated** for architectural drift — they represent history, not current state.

---

*Last updated: 2026-05-08*
*Archive policy: Historical records only — no active guidance*
