---
category: reference
---

# Review-Fix Round Lessons (2026-07-01)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

From fixing review findings on the Max webhook support feature (branch `max-v2`):

- **Single `software-developer` for many small fixes works**: 7 fixes across 6 files dispatched in one brief. Developer applied them all correctly AND fixed a pre-existing test failure as a bonus. Gate 1 review caught 2 issues the developer missed (`logger.exception` misuse, `except Exception` too broad) — the review gate is essential even for "trivial" fixes.
- **`logger.exception` misuse pattern**: When wrapping a call that internally swallows exceptions and returns `False` (like `addUpdate` does), `logger.exception` in the caller has no active exception to attach a traceback to — degrades to plain `logger.error`. Always check whether the upstream call preserves the exception before using `exception()`.
- **`except Exception` too broad for parse errors**: Narrowing to `except (ValueError, OverflowError, TypeError)` for `dateutil.parser.parse` prevents masking genuine DB/programming errors. Specific exception types > broad catches.
- **Pre-existing bugs surface during review**: The `_pollingLoop` marker-advance-on-handler-error issue (marker advances even when a handler raises, defeating at-least-once in deferred mode) is pre-existing and not fixed — the real Max API has the same behavior. Flagged to user as known limitation rather than fixed.
- **Config defaults must align code ↔ config files**: The `unregister-webhook` default was `True` in code but `false` in `00-defaults/webhook-receiver.toml`. Config overrode it in practice, but the inconsistency was confusing. The alignment fix (code default `True` → `False`) was proposed during this round, **landed 2026-07-18** during the docs-audit follow-up (`internal/bot/max/application.py:127` now reads `webhookConfig.get("unregister-webhook", False)`), so the code default now matches `configs/00-defaults/webhook-receiver.toml:23` (`unregister-webhook = false`). Resolved, not an open nit.
- **Doc drift from review fixes is real**: 4 docs (`architecture.md`, `configuration.md`, `developer-guide.md`, `libraries.md`) had stale claims about default values and error behavior after the fix round. Updated via `update-project-docs` skill.
