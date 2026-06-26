# Task-Specific Memories

Archived durable working memory for completed features and subsystems.

Use these files as companions to [`../teamlead-memory.md`](../teamlead-memory.md):

- Keep repo-wide rules, cross-cutting gotchas, and workflow lessons in `teamlead-memory.md`.
- Keep subsystem-scoped discoveries here when they are still useful, but too specific for the main memory file.
- Promote any newly learned repo-wide fact back into `teamlead-memory.md`.
- Never store secrets, tokens, `.env` values, or raw logs.

## Available Files

- [`proxy.md`](proxy.md) — durable notes for `lib/proxy/`, proxy configuration, per-service proxy overrides, HTTP client inventory, and the proxy refactoring anti-patterns.
- [`proxy-lifecycle.md`](proxy-lifecycle.md) — durable notes for the proxy lifecycle management feature: `ProxyService`, `ProxyLifecycle`, subprocess management, health checks, and call-site migration.
- [`sandbox.md`](sandbox.md) — durable notes for `lib/sandbox/`, sandbox config, Docker runtime behavior, and sandbox bot integration.
- [`test-reorganization.md`](test-reorganization.md) — durable notes for the test layout migration (collocated -> `tests/` mirror), conventions, and post-reorg doc audit.
