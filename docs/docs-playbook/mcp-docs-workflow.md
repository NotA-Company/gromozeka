---
title: "Docs workflow via markdown-mcp"
description: "Agent playbook for ongoing documentation work through the markdown-mcp MCP tools"
tags: [playbook, docs]
category: process
---

# Docs workflow via markdown-mcp

Ongoing documentation work in a project already indexed by markdown-mcp. If
the install ships the packaged skill (`markdown_mcp/SKILL.md`), that file is
the authoritative tool contract — exact parameters, response shapes, and
reliability rules. This playbook adds workflow discipline on top of it; it
does not override it.

## Finding things

- `doc_search(query, top_k?, tag?, category?, file_glob?)` is the entry
  point. `top_k` is 1-50, default 8. An empty result means no candidate
  survived the filters AND the score floor — filter values matching
  nothing (unknown values return empty, not errors), excluded or
  not-yet-indexed/stale paths, or scores below `search.min_score`.
  Remove filters or rephrase, then fall back to browsing with
  `doc_list`.
- The filters AND-compose and constrain the candidate set before ranking,
  so the result is the true top-K of the filtered set. `tag` and `category`
  match front-matter values exactly; `file_glob` is fnmatch over
  docs-root-relative paths, where `*` crosses `/` and `**` has no special
  power. Unknown filter values return empty results, not errors.
- Browse metadata before filtering blind: `doc_tags()` and
  `doc_categories()` list every indexed value with the files carrying it.
- `doc_list(tag?, category?, file_glob?)` shows indexed files with title,
  description, and index status — the way to answer "what docs exist".
- `doc_outline(file_path)` returns a file's section tree with slugs and
  line ranges; use it to pick a `section_slug` for a targeted read.

## Read before write

Always `doc_read` the current state before editing — never edit from
memory, and never act on a search snippet alone (snippets are bounded
leading text from a section, not necessarily the passage that made it
relevant).

- `doc_read(file_path)` (disk mode) returns the whole current file from
  disk, capped at 50000 characters, plus a top-level `sha256` that hashes
  the complete file — including content past the display cap.
- `doc_read(file_path, section_slug)` returns that section's stored body
  from the index, capped at 5000 characters (`truncated: true` when cut
  off), plus a top-level `sha256` for the indexed generation. The section's
  exact served body is the `expected_text` CAS basis for section edits.
- Disk content can be newer than the index; use `mode`/`source` to know
  which generation you got.
- Paths matching `[docs].exclude` are readable in disk mode but never
  indexed or searchable.

## Write discipline

The write tools exist only when the config sets `[docs].writable = true`
(default `false`). One gate governs both facades: with the gate off the MCP
tools are absent from tools/list and a call returns `Unknown tool` (do not
retry), and the CLI's `write`/`edit`/`delete` commands fail with
`Edit error:` naming `[docs].writable` — the CLI is not a bypass for the
gate. With the gate off your options are (a) direct filesystem edits
followed by `markdown-mcp index`, or (b) asking the operator to enable
`[docs].writable`.

Every modification is compare-and-swap gated. Never blind-write.

### doc_write - whole documents

`doc_write(file_path, op, content, expected_sha256?)`:

- `op=write` creates a file: the path must not exist and `expected_sha256`
  must be absent.
- `op=overwrite` replaces everything after the front-matter block (front
  matter is preserved); `op=append` adds trailing lines; `op=prepend`
  inserts after front matter, before the first content line. These three
  require `expected_sha256`.

### doc_section_edit - one section

`doc_section_edit(file_path, section_slug, op, expected_text, new_text?)`:

- `op=replace` swaps the section's flat body only; the heading and
  descendant sections are untouched. `new_text` is required here.
- `op=insert_after` inserts a new same-level sibling after the anchor's
  descendants; `new_text` is required and must open with that sibling's
  own heading.
- `op=delete` removes the section with its descendants; `new_text` must be
  absent.
- `expected_text` is the anchor section's complete flat body exactly as the
  section read served it (an empty body is valid; a truncated read is not).
- Never send explicit null for must-be-absent keys — omit them.

### doc_delete

`doc_delete(file_path, expected_sha256)` unlinks the file and removes its
index rows. No backup file is written; version control is the backup story.

### The CAS loop

1. Take the token from `doc_read`: the top-level `sha256` for file-level
   edits and deletion; the section's exact served body as `expected_text`
   for section edits.
2. Make the edit with that token. Every `doc_write`/`doc_section_edit`
   result carries the next `sha256`, so chained edits need no extra read.
3. On a mismatch (`ShaMismatchError`/`SectionTextMismatchError`) the error
   never contains the fresh token — re-read and retry against what you
   observe now, never against a remembered value.
4. Sections over 5000 characters are not section-editable; use whole-file
   `doc_write` operations for those.

### After every write

`doc_write` and `doc_section_edit` return
`{file_path, sha256, outline, reindex}` with
`reindex = {status, sections, embedded}`:

- `indexed` — search, outline, and section reads are current.
- `excluded` — the path matches `[docs].exclude`; the write stands and the
  path stays intentionally unindexed.
- `error` — the disk write stands, but index-backed views may be stale;
  run `markdown-mcp index` later, or `markdown-mcp index --force` (or
  upgrade markdown-mcp first) when the error names a newer schema. A failed
  reindex never undoes the write.
- Use the returned `outline` for slugs. Slugs are NOT stable across edits —
  re-derive them from the outline describing the published generation;
  never cache slugs across tool calls.

## Change hygiene

- Update docs in the same change as the behavior, schema, or config change
  they describe.
- Keep front matter current: title, description, tags, and category should
  describe what the file is now, not what it was.
- Keep `category` within the project's closed category set (see
  [docs-rewrite-playbook.md](docs-rewrite-playbook.md)) so tag/category
  filtering stays meaningful.
- Run lint before declaring done: `doc_lint()` or `markdown-mcp lint`.
  Findings are advisory and never block indexing, but a clean lint is the
  definition of done for docs work.

## Freshness

There is no filesystem watcher. The index changes only when:

- `markdown-mcp serve` starts (startup scan),
- a `doc_write`/`doc_section_edit` call reindexes the touched file
  in-call,
- `markdown-mcp index` runs manually, or
- the deployment sets `[docs].rescan_interval` to a positive number of
  seconds — then the running server's periodic rescan probes the tree each
  interval and reindexes only when files actually changed; with several
  serve processes sharing one database, exactly one elected leader probes.

After out-of-band bulk edits (scripts, rebases, direct file writes), run
`markdown-mcp index`. Index recovery branches by problem class:

- Plain `markdown-mcp index` is an incremental sync. It automatically
  rebuilds when the index is missing, has an older schema, the embedding
  model is incompatible, or the database format is corrupted. A structural
  validation failure (the database opens but fails integrity checks) is
  reported and the command exits without automatic retry — a rebuild may
  then require `markdown-mcp index --force`. Plain `index` refuses to touch
  a NEWER-schema index (created by a newer markdown-mcp) with an "upgrade
  markdown-mcp" message; upgrade the package instead.
- `markdown-mcp index --force` is a deliberate full rebuild; it replaces
  any existing index, including a newer-schema one.

## Pitfalls

- Searching for source-code questions. markdown-mcp answers documentation
  questions; when docs and implementation disagree, the code wins.
- Acting on a snippet without reading the section.
- Editing from memory instead of reading first — CAS rejects you, but
  re-read anyway instead of replaying a remembered token.
- Treating slugs as permanent IDs.
- Calling write tools with the gate off and retrying after `Unknown tool`.
- Sending explicit null for must-be-absent keys (`expected_sha256` on
  create, `new_text` on delete) instead of omitting them.
- Assuming search reflects files changed out-of-band; run
  `markdown-mcp index` first.
- Assuming a whole-file disk read and an indexed section read are from the
  same generation right after an edit.

## Session acceptance checklist

- [ ] Read the current state (`doc_read`) before every edit
- [ ] Every edit carried a CAS token from this session's reads or the
      previous edit result
- [ ] Slugs taken from the edit result's `outline` or a fresh search or
      outline, never from memory
- [ ] Front matter still accurate after the edit; category within the
      project's closed set
- [ ] `reindex.status` handled: `indexed` confirmed, or `error` followed by
      a successful `markdown-mcp index`
- [ ] `doc_lint` (or `markdown-mcp lint`) clean
- [ ] Docs updated in the same change as the code they describe
