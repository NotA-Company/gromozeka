---
title: "Docs rewrite playbook"
description: "One-time agent playbook for cleaning up an existing docs tree for markdown-mcp"
tags: [playbook, docs]
category: process
---

# Docs rewrite playbook

One-time cleanup of an existing, messy Markdown docs tree so that
markdown-mcp search and navigation work well. Run this once when a project
adopts markdown-mcp on docs that have drifted; afterwards, keep the tree
healthy with the ongoing workflow in
[mcp-docs-workflow.md](mcp-docs-workflow.md).

Assumption: markdown-mcp is configured for the project (a
`.markdown-mcp.toml` whose `[docs].root` points at the docs tree). If not,
configure it first — every phase below runs `lint` or `index` against the
real tree.

## Ground rules

- Read the target project's `AGENTS.md` (or its conventions doc) before
  touching anything. Project conventions win on every conflict with this
  playbook.
- Archive; do not delete. Move stale material into an archive directory.
  Deletion is the project owner's decision, not the agent's.
- Work in small batches. Commit per phase so each phase is reviewable and
  revertible on its own.
- Never break existing links. After each batch, run the project's link
  checker (or a grep-based pass over relative links) and fix every link you
  orphaned before committing.
- Do not change what documents say. This playbook moves, splits, retitles,
  and adds metadata; it does not rewrite content.

## Phase 0 - Orient

1. Inventory the tree: list every `.md` file under the docs root; note
   counts, languages, and obvious strays (session dumps, plan leftovers,
   duplicate topics).
2. Run `markdown-mcp lint`. It parses the tree directly, so it needs no
   index and no embedding model — safe on a fresh checkout and in CI — and
   exits 1 when it has findings. Record the baseline finding count per rule.
3. Decide the live-vs-archive split. Current contracts and day-to-day
   guidance stay; completed plans, superseded designs, and session notes
   move to the archive directory.
4. Ensure `[docs].exclude` in `.markdown-mcp.toml` covers the archive
   directory (for example `exclude = ["archive/"]`). Lint and the index both
   skip excluded paths, so archived files need no cleanup to pass Phase 5.
5. Run `markdown-mcp index` for a baseline index and record its counts.

## Phase 1 - Triage and archive

- Move completed plans, stale self-declared documents (files that announce
  themselves as drafts, notes, or scratch), and session dumps into the
  archive directory. Use `git mv` so history follows.
- Re-run `markdown-mcp index`. The scan removes index rows for files that
  left the tree or moved into excluded paths; confirm the `deleted=` count
  matches your moves.
- Verify the index no longer sees archived content: search for a phrase
  that existed only in a moved file and confirm no results.
- Commit.

## Phase 2 - Structure

- Give every file exactly one H1. `duplicate-h1` lint findings flag the
  violators; the first H1 (or the front-matter title) is the document title.
- H1 is title metadata, not a section: it is not an indexed section. Every
  H2-H6 heading creates a section row, but only sections with a non-empty
  flat body receive an embedding and are searchable. Put searchable content
  under H2-H6 headings; each stored section is individually searchable and
  readable.
- Fix `duplicate-slug` findings by rewording headings. Do not rely on the
  automatic `-2` suffixes; links and agents reference slugs.
- Break up files with `oversized-section` findings: the finding fires on a
  flat section body over 5000 characters. The generic markdown-mcp default
  section-read cap is also 5000, but this repo overrides it to 8192
  (`section_read_cap` in `.markdown-mcp.toml`, owner-ratified 2026-09-06);
  sections over the cap truncate on read and cannot be section-edited.
  Split the topic into child sections or move detail into a new file.
- Create or refresh a docs-root README or index page as the entry point:
  short, linking the main documents. Link; do not duplicate content.

## Phase 3 - Front matter

The recommended default shape for every live (non-archived) file:

```yaml
---
title: "Adding a handler"
description: "End-to-end recipe for registering a handler"
tags: [handlers, recipes]
category: guide
---
```

- markdown-mcp itself treats all four fields as optional: unknown fields
  are ignored and invalid front matter never blocks indexing. Apply the
  four-field shape as the recommended default, but defer strictness (which
  fields are required, tag vocabulary and limits) to the consuming
  project's own conventions, and record whatever the project adopts.
- `title` and `description` are strings; `tags` is a list of strings;
  `category` is a single value. `description` is file-level metadata
  surfaced by `doc_list` (MCP) and the CLI's `list --json`; the CLI's
  human-readable `list` output does not display it. It never enters
  section embeddings, so do not stuff keywords into it.
- Tags and the category must be kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`);
  the `non-kebab-tag` and `non-kebab-category` lint rules flag violations.
- A small closed category set (4-6 values) — for example `design`,
  `guide`, `process`, `reference`, `evidence` — keeps tag/category
  filtering meaningful. markdown-mcp itself treats category values as
  free-form strings; the closed set is the consuming project's own
  convention, enforced by review, not by the tool. One category per file.
- Archived files are exempt: lint and the index both skip excluded paths,
  so archive content needs no front-matter compliance.
- Commit.

## Phase 4 - Normalize

- Make each file single-language. Mixed-language content degrades embedding
  quality and search results; split or translate rather than interleave.
- Strip emojis if the project forbids them; check the project's
  conventions first.
- Split giant single-line paragraphs into normal prose so section snippets
  and reads stay usable.

## Phase 5 - Verify

1. `markdown-mcp lint` returns zero findings (exit 0). Excluded archive
   paths are skipped; only live docs are judged.
2. `markdown-mcp index` completes with `errors=0`.
3. Search smoke tests: run 5-10 realistic questions through
   `markdown-mcp search` and confirm each returns the document you would
   hand to a human.
4. Link check passes (the project's checker or your grep-based pass).
5. Commit.

## Tool choice

- Bulk restructuring — moving files, splitting documents, re-heading — is
  fastest with direct file operations (or whole-file `doc_write`) followed
  by one `markdown-mcp index` to sync everything.
- Fine-grained upkeep — rewriting one section in place — fits
  `doc_section_edit`; reach for it after the rewrite, during normal
  workflow, not inside a bulk sweep.
- The edit surface exists only when the config sets `[docs].writable = true`
  (default `false`), and one gate governs both facades: with the gate off
  the MCP edit tools are absent, and the CLI's `write`/`edit`/`delete`
  commands fail with `Edit error:` naming `[docs].writable` — the CLI is
  not a bypass for the gate. With the gate off, the options are (a) direct
  filesystem edits followed by one `markdown-mcp index`, or (b) asking the
  operator to enable `[docs].writable`.

## Acceptance checklist

- [ ] Archive directory exists, is covered by `[docs].exclude`, and holds
      all completed plans, stale docs, and session dumps
- [ ] Every live file has exactly one H1, and front matter follows the
      project's adopted metadata policy (recommended default: title,
      description, kebab-case tags, and a category from the project's
      closed set)
- [ ] `markdown-mcp lint` exits 0 with zero findings
- [ ] `markdown-mcp index` completes with `errors=0`
- [ ] Search smoke tests return the expected documents
- [ ] No existing links are broken (link checker or grep pass clean)
- [ ] Docs-root entry-point README or index exists and links the main
      documents
- [ ] Project conventions record the closed category set
- [ ] Each phase committed separately
