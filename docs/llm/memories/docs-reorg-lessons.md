# Docs Reorg Lessons (2026-07-04)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

- When bulk-moving docs with `git mv`, sibling-relative links INSIDE the moved files are the easy-to-miss gap. A dev reported "fixed relative links" but Gate 1 review caught 3 unfixed sibling links in a retained doc pointing to a moved companion. Always grep the moved files' OWN content for sibling refs after relocation.
- Source-tree READMEs (`lib/*/README.md`, `internal/services/*/README.md`) and code-doc comments (`*.py` docstrings, migration module docstrings) also reference design/plan docs — these are easy to miss because they're outside `docs/`. Grep `lib/` and `internal/` for `docs/plans/` and `docs/design/` paths, not just `docs/`.
- `configs/00-defaults/*.toml` files carry doc-path references in comments (e.g. `# See docs/plans/chat-history-search-plan.md`). These need repointing too.
- A status-line-only edit can create an internal contradiction if the doc has a separate `Scope:` line making similar claims — reconcile ALL status/scope/phase headers, not just the one flagged.
- For docs-only reorgs: `make lint` is the only needed gate (no `make test`); black/isort are no-ops on .md and comment-only .py edits.
