---
description: Add or draft a CHANGELOG.md entry from the current diff (Keep a Changelog format)
agent: software-developer
subtask: true
---
Manage the `## [Unreleased]` section of `CHANGELOG.md` (Keep a Changelog format).
The full process, format, and "when / when-not to update" rules live in
`docs/llm/changelog.md` — read it first if unsure how to classify or phrase an entry.

Evaluate `$ARGUMENTS` in this exact order; the FIRST matching branch wins and
the rest are ignored. This is a non-interactive command: never block on user
input — either make a decision (and state the assumption in your summary) or
abort with a short message.

## Branch 1 (release cut) — `$ARGUMENTS` begins with `cut` or `release`

This matches `/changelog cut`, `/changelog cut 1.2.0`, `/changelog release`,
and `/changelog release 1.2.0`.

Perform a release cut: rename the current `## [Unreleased]` heading to a dated
version heading `## [X.Y.Z] - YYYY-MM-DD`, and add a fresh, empty
`## [Unreleased]` section above it. Follow the semver bump rules in
`docs/llm/changelog.md`.

The version is taken from the argument (the token after `cut`/`release`):
`/changelog cut 1.2.0` or `/changelog release 1.2.0`. If NO version is supplied
(`/changelog cut` or `/changelog release` with nothing after it), do NOT guess
a version and do NOT ask — ABORT instead with a one-line message telling the
user to re-invoke it as `/changelog cut <X.Y.Z>` and stating the semver bump
rule from `docs/llm/changelog.md`.

## Branch 2 (entry text) — `$ARGUMENTS` is any OTHER non-empty text

Treat `$ARGUMENTS` as the entry text. It may optionally be prefixed with the
category, e.g. `fixed: ...`, `added: ...`, `changed: ...`; otherwise infer the
category from the text. Insert under `## [Unreleased]` in the matching
`### Added` / `### Changed` / `### Fixed` subsection, creating that subsection
if it does not yet exist. Preserve existing ordering. Keep a `## [Unreleased]`
heading present at all times, even if it ends up empty.

## Branch 3 (diff inspection) — `$ARGUMENTS` is empty

- Inspect the current change: `git diff` (staged and unstaged). If nothing is
  staged/changed, fall back to the most recent commit via `git log -1` (and a
  few more if needed).
- Decide whether the change warrants an entry using the "When to update" /
  "When NOT to update" rules in `docs/llm/changelog.md`. If it does NOT warrant
  one (style/formatting fix, internal refactor with no user-visible effect,
  doc-only tweak unless documenting a new feature, test-only change), say so
  briefly and stop — do not add an entry.
- Classify the change into Added / Changed / Fixed and draft ONE concise line
  in the documented entry style: start with the thing that changed (NOT
  "Added"/"Fixed"), name the user-facing surface (command / config key / tool
  / file path), past tense, declarative, include the why only when non-obvious.
- Insert the line under `## [Unreleased]` in `CHANGELOG.md`, in the matching
  `### Added` / `### Changed` / `### Fixed` subsection, creating that subsection
  if it does not yet exist. Preserve existing ordering. Keep a `## [Unreleased]`
  heading present at all times, even if it ends up empty.

If the diff is ambiguous, do NOT ask — make a best-effort classification
decision, insert the entry, and STATE the assumption you made in your summary.
Never fabricate capabilities: if the diff genuinely reveals no user-facing
change, fall back to the "when NOT to update" rule above rather than inventing
one.
