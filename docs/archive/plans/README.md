# Archived Plans

> **Status:** Historical implementation plans — not active guidance
> **Warning:** May contain stale file paths, superseded architectures, or completed-but-unmarked work

---

## Overview

This directory contains **historical implementation plans** for features that have
been completed, superseded, or abandoned. They are kept for audit trail and
design-rationale reference, not as current implementation guidance. Before acting
on any plan here, verify the feature's current state against the live codebase
and [`docs/llm/`](../../llm/).

## Recently Archived (2026-07-04)

These plans were moved out of `docs/plans/` once their features shipped or the
plan was superseded:

- [`python-sandboxing-v0.gpt.md`](python-sandboxing-v0.gpt.md) — Early GPT brainstorm; superseded by v1.
- [`python-sandboxing-v0.gemini.md`](python-sandboxing-v0.gemini.md) — Early Gemini brainstorm; superseded by v1.
- [`python-sandboxing-v1-implementation.md`](python-sandboxing-v1-implementation.md) — Build-order work-package; fully executed.
- [`python-sandboxing-v1-integration.md`](python-sandboxing-v1-integration.md) — Gromozeka-side glue design; implementation diverged (shipped as [`internal/bot/common/handlers/sandbox.py`](../../../internal/bot/common/handlers/sandbox.py)).
- [`python-sandboxing-v1-rc1.md`](python-sandboxing-v1-rc1.md) — Intermediate draft; superseded by v1 final.
- [`proxy-support.md`](proxy-support.md) — Implemented in [`lib/proxy/`](../../../lib/proxy/) (refactored from plan).
- [`proxy-lifecycle-design.md`](proxy-lifecycle-design.md) — Implemented in [`internal/services/proxy/`](../../../internal/services/proxy/) (`service.py`, `lifecycle.py`).
- [`condensing-prompt-split.md`](condensing-prompt-split.md) — Implemented; self-declared. `ChatSettingsKey.CONDENSING_SYSTEM_PROMPT`.
- [`media-group-completion-detection.md`](media-group-completion-detection.md) — Implemented in `resender.py` + media attachments repo.
- [`test-reorganization.md`](test-reorganization.md) — Completed 2026-05-21; all tests now under `tests/`.
- [`llm-replay-and-yaml-conversion.md`](llm-replay-and-yaml-conversion.md) — `/llm_replay` command + `convert_readable_to_llm_log.py` shipped.
- [`memory-refine-plan-v0.md`](memory-refine-plan-v0.md) — Abandoned brainstorm stub ("I want following").
- [`internal-lib-docstring-processing-plan.md`](internal-lib-docstring-processing-plan.md) — Completed docstring pass (stages 1-8).
- [`max-api-migration.md`](max-api-migration.md) — Implemented; Max API migrated to `platform-api2.max.ru`.
- [`max-webhook-support.md`](max-webhook-support.md) — Implemented; two-process webhook mode (ADR-013).
- [`chat-history-search-plan.md`](chat-history-search-plan.md) — Step 1 delivered; superseded by step2.
- [`chat-history-search-step2.md`](chat-history-search-step2.md) — Fully implemented (`/users`, 3 LLM tools).
- [`lib-stats-stats-library-v2.md`](lib-stats-stats-library-v2.md) — Superseded by v3.
- [`lib-stats-stats-library-v3.md`](lib-stats-stats-library-v3.md) — Implemented in [`lib/stats/`](../../../lib/stats/) + [`internal/database/stats_storage.py`](../../../internal/database/stats_storage.py).
- [`lib-stat-stats-library.md`](lib-stat-stats-library.md) — v1; two generations superseded.
- [`resender-forward-feature.md`](resender-forward-feature.md) — Implemented in `resender.py` (`forwardTo`) + `bot.forwardMessages`.
- [`yc-sdk-provider-refactoring.md`](yc-sdk-provider-refactoring.md) — Implemented in [`lib/ai/providers/yc_sdk_provider.py`](../../../lib/ai/providers/yc_sdk_provider.py).

## Using This Archive

### For Historical Context
✅ Read when you want to understand:
- Why a feature was built a certain way
- What build order or staging was attempted
- The evolution of a component across revisions

### For Implementation Reference
❌ Do NOT use as current implementation guidance. Before code changes:
1. Verify file/directory paths exist
2. Check current code structure
3. Cross-reference with active docs in [`docs/llm/`](../../llm/)

---

*Last updated: 2026-07-04*
*Plans archive maintained for historical context only*
