# Changelog Process

A lightweight, agent-friendly process for maintaining a `CHANGELOG.md` that stays accurate without becoming a chore. Designed for projects where an AI agent does most of the coding — the changelog is updated as part of the work, not as an afterthought.

> This is the canonical changelog process for the project. `AGENTS.md` carries a compact summary; this document is the full spec.

## Purpose

The changelog is the **user-visible record of what changed and why**. It's not a commit log (those are too granular) and not release notes (those are a subset, cut at release time). It's the running narrative a maintainer reads to understand how the project evolved.

## When to Update

Update `CHANGELOG.md` **as part of the same change** that introduces the behavior. The agent (or developer) adds the entry when the work is done, before committing.

Add an entry for:

- **New features** — new tools, commands, config fields, public APIs
- **Bug fixes** — anything that changes runtime behavior to fix a defect, especially root-cause fixes with non-obvious causes
- **Behavioral changes** — defaults changed, output format changed, deprecations, removed features
- **Schema/data migrations** — database schema bumps, config format changes
- **Documentation** — *only when documenting a new feature* (not for doc-only tweaks)

## When NOT to Update

Skip the changelog for:

- Minor style/formatting fixes (lint, prettier, whitespace)
- Internal refactors with no user-visible change (moving code between files, extracting helpers, renaming internal variables)
- Documentation-only updates that don't describe a new feature
- Test additions or test-only refactors
- Dependency bumps with no behavioral change

If in doubt, ask: *would a user or future maintainer need to know about this to understand the project's evolution?* If no, skip it.

## Format

Follow [Keep a Changelog](https://keepachangelog.com/) conventions:

```markdown
# Changelog

All notable changes to this project.

## [Unreleased]

### Added
- New feature or capability, described in one concise line

### Changed
- Something that was modified in behavior, one concise line

### Fixed
- A bug that was resolved, one concise line

## [1.0.0] - 2025-01-15

### Added
- Initial release
```

### Categories

| Category | Use for |
|----------|---------|
| **Added** | New features, capabilities, config fields, commands, APIs |
| **Changed** | Changes in existing functionality, defaults, output, format |
| **Fixed** | Bug fixes and defect corrections |

Add `Removed` and `Deprecated` categories only if the project actually uses them.

### Entry Style

- **One line per entry.** If it needs a paragraph, split it or link to docs.
- **Start with the thing that changed**, not with "Added" or "Fixed" (the category already says that).
- **Include the why** when it's not obvious — root cause for fixes, rationale for decisions.
- **Name the user-facing surface** — command names, config keys, tool names, file paths. A reader should be able to find the thing in the codebase.
- **Past tense, declarative.** "Search stats now record the agent and model" not "We are recording the agent and model."

Good:

```
- `/memory stats` now includes a zero-result rate per search path
```

Bad:

```
- Improved the stats command
- We fixed an issue where stats were sometimes wrong
```

## The `[Unreleased]` Section

All in-progress entries accumulate under `## [Unreleased]`. This section is always present, even when empty — it's the staging area for the next release.

When cutting a release:

1. Review the `[Unreleased]` section — make sure it covers everything since the last release.
2. Replace the `## [Unreleased]` heading with a dated version heading: `## [1.2.0] - 2025-07-14`.
3. Add a fresh, empty `## [Unreleased]` section above it for future work.

Before:

```markdown
## [Unreleased]

### Added
- Feature X

### Fixed
- Bug Y
```

After:

```markdown
## [Unreleased]

## [1.2.0] - 2025-07-14

### Added
- Feature X

### Fixed
- Bug Y
```

### Initial baseline (one-time exception)

A project's first `CHANGELOG.md` may begin with a one-time dated baseline section, `## Initial State - YYYY-MM-DD` (with `### Added`), to snapshot capabilities that already exist before the first versioned release. This deliberately deviates from the `## [X.Y.Z] - YYYY-MM-DD` heading format so an existing-but-unreleased project can be captured without inventing a fake semver tag. Once that baseline exists, the first versioned release (and every release after) follows the standard bracketed format above.

## Release operations (version bump, commit, tag, push)

The heading cut described above (rename `## [Unreleased]` → `## [X.Y.Z] - YYYY-MM-DD`, insert a fresh empty `## [Unreleased]` above it) is only the first step of cutting a release. The full release procedure is the cut **plus** the three operations below. Do them in order, as a single atomic unit of work.

### (a) Bump the version field

Update `version` under `[project]` in `pyproject.toml` to match the new `## [X.Y.Z] - YYYY-MM-DD` heading:

```toml
[project]
name = "gromozeka"
version = "1.0.0"
```

`pyproject.toml`'s `[project].version` is the **canonical machine-readable** version source; the CHANGELOG release heading is the **human-readable** mirror. The two MUST stay in sync — anyone tooling off the project (build scripts, packaging, release tooling) reads `pyproject.toml`, anyone reading release notes reads the CHANGELOG.

### (b) Commit the release

Stage and commit the release as a single atomic commit including:

- `CHANGELOG.md` — the cut (renamed heading + fresh empty `## [Unreleased]`).
- `pyproject.toml` — the version bump.
- Any other files modified as part of the release prep (migration scripts, README updates, dep bumps, etc.) — review `git status` and include anything thematically part of the release.

Suggested commit message: `Release v<X.Y.Z>` (e.g. `Release v1.0.0`).

### (c) Tag and push

Create an **annotated** git tag and push it:

```bash
git tag -a v<X.Y.Z> -m "Release v<X.Y.Z>"
git push origin v<X.Y.Z>
```

Annotated tags (`-a`) are preferred over lightweight tags for releases — they record tagger, date, and message per git convention, and `git describe` / release tooling relies on them.

### Automation

The `/generate-release <version>` slash-command (see `.opencode/commands/generate-release.md`) automates the whole sequence end-to-end: heading cut, version bump, commit, annotated tag, push. Use it when the release is straightforward; fall back to the manual steps above when you need to stage additional files or split the work. `/generate-release <X.Y.Z>` is the full release sequence (cut + version bump + commit + tag + push); `/changelog cut <X.Y.Z>` does only the CHANGELOG heading rename (a subset of the full sequence) and is useful when you want to stage the cut separately from the rest of the release operations.

## Versioning

Use [semver](https://semver.org/) (`MAJOR.MINOR.PATCH`):

| Bump | When |
|------|------|
| **patch** | Bug fixes, minor tweaks, doc updates with behavioral fixes |
| **minor** | New features, new config fields, new commands, additive schema changes |
| **major** | Breaking changes, removed features, schema changes requiring data reset |

This project does not publish to a registry, but version bumps are still useful for tracking. The canonical machine-readable version source is `[project].version` in `pyproject.toml`; the CHANGELOG release heading is the human-readable mirror. The two MUST stay in sync — see [Release operations](#release-operations-version-bump-commit-tag-push) above.

## Agent Instructions

The sections above are the canonical changelog guidance for AI coding agents on this project. [`AGENTS.md`](../../AGENTS.md) carries a compact summary of these rules; this document is the authoritative source — if the rules are amended, keep `AGENTS.md`'s summary consistent with what is written here, not the other way around. The condensed reminder below mirrors this document's own "When to Update" / "When NOT to Update" sections:

```markdown
## Changelog

Update `CHANGELOG.md` **as part of the same change**, before committing, when the
work introduces:

- A new feature (new tool, command, config field, or public API)
- A bug fix (especially a non-obvious root-cause fix)
- A behavioral change (changed default, output format, deprecation, removed feature)
- A schema/data migration (database schema bump, config format change)
- Documentation *only* when it describes a new feature

Add the entry under the matching category (Added / Changed / Fixed), one concise line.

Do NOT add an entry for:

- Minor style/formatting fixes
- Internal refactors with no user-visible change
- Documentation-only updates that don't describe a new feature
- Test additions or test-only refactors
- Dependency bumps with no behavioral change
```

This gives the agent a clear trigger (new feature, bug fix, behavioral change, schema migration, or feature-introducing docs) and a clear stop (no user-visible change = no entry). The agent updates the changelog as part of the work, not as a separate step.
