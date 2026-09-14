---
title: "gromozeka docs workflow brief"
description: "Ongoing agent briefing for docs work in gromozeka via markdown-mcp"
tags: [playbook, gromozeka]
category: process
---

# gromozeka docs workflow brief

You are the agent working in the gromozeka repository
(`/Users/vgoshev/Development/NotA/gromozeka`). This briefing describes how to
find, read, and edit the project's documentation through the markdown-mcp MCP
server. gromozeka's `AGENTS.md` wins on any conflict with this brief.

## The setup (actual gromozeka configuration)

- `.markdown-mcp.toml` at the repo root: `[docs] root = "./docs"`,
  `exclude = ["archive/", "other/"]`, `writable = true`,
  `rescan_interval = 30`. The `[index]` keys are commented out, so
  defaults apply: index database at `./.markdown-mcp/index.db` (gitignored)
  and the `e5-small` embedding model. No `[search].min_score` is set, so
  the built-in default applies.
- Registered in the **global** `~/.config/opencode/opencode.jsonc` (under
  `mcp."markdown-mcp"`) as a local MCP server running
  `markdown-mcp --use-global-config serve`; the project
  `.opencode/opencode.json` has no `mcp` block. The repo-root
  `.markdown-mcp.toml` is found by markdown-mcp's walk-up config
  discovery, not by a `MARKDOWN_MCP_CONFIG` env var.
- Because `writable = true`, tools/list has ten tools: seven read tools
  (`doc_search`, `doc_list`, `doc_tags`, `doc_categories`, `doc_outline`,
  `doc_read`, `doc_lint`) plus the gated edit tools (`doc_write`,
  `doc_section_edit`, `doc_delete`). The CLI mirrors them: `markdown-mcp
  index`, `search`, `read`, `write`, `edit`, `delete`, `list`, `tags`,
  `categories`, `lint`, `config show`, `stats`, `serve`.
- `docs/archive/` and `docs/other/` are excluded: files there are never
  indexed or searchable. Searchable docs are the live tree only.
  `docs/other/` (third-party API dumps) is direct-access-only — enter it
  via its `docs/other/README.md` index, which is linked from
  `docs/README.md`. To read an excluded file, read it directly from disk —
  `doc_read` still serves excluded paths, or use your normal file-read
  tool.

## Finding docs

- Start with `doc_search(query)`. `top_k` is 1-50 (default 8). Optional
  filters `tag`, `category`, `file_glob` AND-compose and constrain the
  candidate set before ranking. `tag` and `category` match front-matter
  values exactly; `file_glob` matches the docs-root-relative path with
  fnmatch (same dialect as the `exclude` config), where `*` crosses `/`
  and `**` has no special meaning.
- An empty result is not an error — it means no candidate survived the
  filters AND the score floor. Common causes: unknown filter values (an
  empty result, not an error), excluded or stale (not-yet-indexed) paths,
  and scores below `min_score`. Rephrase the query (different wording, not
  just shorter), drop filters to widen the candidate set, or browse
  instead of searching.
- Browse with `doc_list(tag?, category?, file_glob?)` (indexed files with
  title and description), `doc_tags()`, and `doc_categories()` (every value
  in use, with file lists). Check these before inventing a new tag or
  category value.
- Before a deep read, call `doc_outline(file_path)` — it returns the file's
  sections with slugs, levels, and line ranges. Pick the section slug from
  the outline instead of reading whole files.
- Search snippets are bounded leading text from a section, not necessarily
  the passage that made it relevant. Always `doc_read` the section before
  acting on a snippet.

## Reading discipline

`doc_read(file_path, section_slug?)` has two modes:

- With `section_slug`: the section's stored body from the index, capped at
  8192 characters (`truncated: true` means cut off).
- Without it: the whole current file from disk, capped at 65536 characters.
  Disk content can be newer than the index; trust the `mode`/`source` in the
  response to know which generation you got.

(The caps above are this repo's owner-ratified overrides, set on 2026-09-06
in `.markdown-mcp.toml` `[read]`: `section_read_cap = 8192`,
`disk_read_cap = 65536`. The generic defaults these override are
5000/50000.)

Both modes return a top-level `sha256`. You never compute hashes yourself —
these are the compare-and-swap (CAS) tokens the edit tools consume. Rule:
always read before write, and use the section read (not a whole-file read)
as the basis for a section edit.

## Writing discipline

Every modification is CAS-gated — never blind-write:

1. `doc_read` the file (disk mode) or the target section.
2. For file-level edits and deletion pass that result's `sha256` as
   `expected_sha256`. For section edits pass `expected_text`: the section's
   complete flat body exactly as the section read served it (an empty body is
   valid; a truncated read is not — such sections are not section-editable).
3. On a mismatch — `ShaMismatchError` for file-level tokens,
   `SectionTextMismatchError` for section edits — the edit aborts with the
   file untouched and the error never includes the fresh token. Re-read and
   retry against what you observe now, never against a remembered value.

Omit parameters entirely when the contract says they must be absent — e.g.
`expected_sha256` on a create — instead of passing an explicit null.

- `doc_write(file_path, op, content, expected_sha256?)`: `write` creates a
  file (path must not exist, token absent), `overwrite` replaces everything
  after the front-matter block, `append` adds trailing lines, `prepend`
  inserts after front matter before the first content line. The three
  modify ops require `expected_sha256`.
- `doc_section_edit(file_path, section_slug, op, expected_text, new_text?)`:
  `replace` swaps only the section's flat body — its heading and descendant
  sections are untouched; `insert_after` adds a new same-level sibling after
  the anchor's descendants, and `new_text` must open with that sibling's own
  heading; `delete` removes the section with its descendants. `new_text` is
  REQUIRED for `replace` and `insert_after` and must be ABSENT for
  `delete` — omit it, never pass an explicit null.
- Use `doc_section_edit` only when the section's complete flat body is
  available and the section read was not truncated (the configured
  `section_read_cap` is 8192 — see `.markdown-mcp.toml`); there is no
  second independent size cap. For a truncated read, edit the whole file
  with `doc_write`.
- `doc_write` and `doc_section_edit` publish atomically and attempt an
  in-call single-file reindex. Inspect `reindex.status`: `indexed` means
  search, outline, and section reads are current; `excluded` means the path
  is intentionally unindexed (expected only under the excluded `archive/`
  and `other/` prefixes — investigate anywhere else); `error` means the
  write stood but index-backed views may be stale — run `markdown-mcp
  index` before trusting them.
- Both tools return `{file_path, sha256, outline, reindex}`. The `sha256` is
  the next CAS token: chained edits to the same file need no extra read.
  Slugs are not stable across edits — after every edit, take slugs from the
  returned `outline` (it always describes the published generation), not
  from your memory of the previous outline.
- `doc_delete(file_path, expected_sha256)` unlinks the file and removes its
  index rows. No backup file is written; version control is the backup
  story — commit before deleting.

## gromozeka doc rules (cite the sources, follow them)

- Follow gromozeka `AGENTS.md`; it links `docs/llm/index.md` as the
  canonical deeper guide. Both list the instruction sources and say: do not
  duplicate, prefer linking.
- `docs/database-schema.md` and `docs/database-schema-llm.md` must be kept
  in sync manually when the schema changes (AGENTS.md, "Existing instruction
  sources"). If you change one, check the other.
- For review or restructuring work, follow
  `docs/documentation-review-process.md` — including its Archival Criteria
  for moving material into `docs/archive/` (historical only, never updated
  for drift).
- Use gromozeka's own skills when their triggers apply:
  `read-project-docs` (onboarding/context before non-trivial work) and
  `update-project-docs` (post-change documentation sync with a decision
  matrix).
- CHANGELOG: per AGENTS.md, doc-only tweaks are skipped unless they
  document a new feature. Check `docs/llm/changelog.md` when unsure.
- Front matter (when the live tree carries it): `category` must come from
  the project's closed five-value set decided in the docs rewrite —
  `design`, `plan`, `process`, `guide`, `reference` (the rewrite brief's
  Phase 4 records the policy) — and tags must be kebab-case values from
  the recorded vocabulary (check `doc_tags()` / `doc_categories()` first).
  Do not invent new values without recording them where the vocabulary is
  defined (`AGENTS.md` or `docs/README.md`).
- Gate every docs change with gromozeka's mandatory sequence (AGENTS.md
  "Run / dev commands", `docs/llm/index.md` §3.5): `make format lint`
  BEFORE edits; after edits run `make format lint`, then `make test`
  (mandatory after any change, docs-only edits included), then
  `make check-docs` (local markdown link checker; exit 1 on broken links),
  plus `markdown-mcp lint` for the docs tree.

## Freshness

- There is no filesystem watcher. The index updates when: `markdown-mcp
  serve` starts (startup scan), a `doc_write`/`doc_section_edit` call
  reindexes the touched file in-call, `markdown-mcp index` runs (manual,
  incremental), or the periodic rescan fires.
- gromozeka sets `rescan_interval = 30`: every 30 seconds the server
  stat-probes the tree (read-only, drift-checked) and reindexes only when
  files actually changed. When several serve processes share the database,
  one elected leader probes. Normal lag is about one interval, more under
  lock contention.
- After bulk out-of-band changes — git branch switches, merges, rebases,
  scripted mass edits — run `markdown-mcp index` yourself instead of
  waiting out the rescan.
- Stale-index symptoms: a doc you just wrote outside the tools is not
  searchable; `doc_outline` misses sections you know exist. Fix: run
  `markdown-mcp index`.
- Index recovery branches by problem class:
  - Plain `markdown-mcp index` is an incremental sync. It automatically
    rebuilds when the index is missing, has an older schema, the embedding
    model is incompatible, or the database format is corrupted. A structural
    validation failure (the database opens but fails integrity checks) is
    reported and the command exits without automatic retry. Plain `index`
    refuses to touch a NEWER-schema index (created by a newer markdown-mcp)
    with an "upgrade markdown-mcp" message; upgrade the package instead.
  - Generic tool capability, NOT permitted in this repo: `markdown-mcp
    index --force` is a deliberate full rebuild that replaces any existing
    index, including a newer-schema one. The repo rule is never `--force`
    (the embedding rebuild times out); incremental `markdown-mcp index`
    repairs partial rebuilds, and if it cannot repair the index, escalate
    recovery to the owner.
- `markdown-mcp config show` prints the resolved configuration if the setup
  ever looks wrong; `markdown-mcp stats` shows index health.

## Pitfalls

- Do not assume an empty search result means the doc does not exist — it
  may be below `min_score`, filtered out, or excluded (`archive/`,
  `other/`).
- Do not treat slugs as permanent IDs; re-derive them from outlines after
  any edit.
- Do not section-edit a truncated section read — it is not section-editable.
- Do not retry a CAS mismatch against a remembered token; re-read first.
- Do not write to `docs/archive/` with the edit tools expecting search to
  see it — the path is excluded by design.
- Do not duplicate rule text between AGENTS.md and `docs/llm/`; link.
- Do not run ad-hoc mass rewrites through the edit tools one section at a
  time when a scripted change plus one `markdown-mcp index` is the honest
  shape — but commit first, and verify with `make check-docs`.

## Session acceptance checklist

- [ ] Reads used outlines and targeted section reads; snippets were verified
      with `doc_read` before acting on them.
- [ ] Every write followed the CAS loop; no mismatch was retried against a
      stale token; chained edits used the returned `sha256`.
- [ ] Every `reindex.status` other than `indexed` was handled (`markdown-mcp
      index` after `error`; investigate unexpected `excluded`).
- [ ] Front matter follows the decided category set (five values; recorded
      by the rewrite brief's Phase 4) and tag vocabulary.
- [ ] Zero markdown-mcp lint findings (`doc_lint` or CLI) — the acceptance
      bar once the one-time rewrite establishes the clean baseline.
- [ ] gromozeka's gate sequence ran around every edit: `make format lint`
      BEFORE edits and again after, then `make test` (mandatory after any
      change), then `make check-docs`; a single invocation — before-only or
      after-only — cannot satisfy this. Zero markdown-mcp lint findings
      (item above).
- [ ] Out-of-band bulk edits were followed by `markdown-mcp index`.
