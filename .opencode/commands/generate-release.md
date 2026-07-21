---
description: Execute the full release process for a new version — CHANGELOG cut, pyproject version bump, commit, annotated git tag, and tag push
agent: teamlead
subtask: true
---
Cut a release for version `$ARGUMENTS`. This coordinates the full release
sequence: CHANGELOG cut, `pyproject.toml` version bump, commit, annotated git
tag, and tag push. The canonical spec for the per-step contract lives in
`docs/llm/changelog.md#release-operations-version-bump-commit-tag-push` — read
it first if unsure how any individual step should behave.

This is a non-interactive command: never block on user input. Either make a
best-effort decision (and state the assumption in the final report) or abort
cleanly with a one-line message. The version is NEVER guessed.

## Step 0 — Validate `$ARGUMENTS`

First, strip leading/trailing whitespace from `$ARGUMENTS`. Then evaluate in
this order; the first matching branch wins.

### Branch 0a — empty

If `$ARGUMENTS` is empty (no version supplied), ABORT with exactly this
message and stop:

```
No version supplied. Re-invoke as `/generate-release <X.Y.Z>` (e.g.
`/generate-release 1.2.0`). Semver bump rules: patch=bugfixes, minor=new
features, major=breaking changes (see `docs/llm/changelog.md`).
```

### Branch 0b — invalid

If `$ARGUMENTS` is non-empty but does NOT match the strict semver regex
`^\d+\.\d+\.\d+$`, ABORT with the same message as Branch 0a. Reject
pre-release / build metadata variants (`1.0.0-rc1`, `1.2.3+build4`) — users
who want those should run the steps manually. Examples of valid input:
`1.0.0`, `1.2.3`, `0.4.10`.

### Branch 0c — valid

Otherwise `$ARGUMENTS` is the release version (`<VERSION>`). Continue to
Branch 0d before proceeding.

### Branch 0d — detached HEAD

If HEAD is detached (`git symbolic-ref -q HEAD` returns non-zero, or
`git rev-parse --abbrev-ref HEAD` returns `HEAD`), ABORT with exactly this
message and stop:

```
HEAD is detached. Checkout a release branch first (e.g. `git checkout master`)
and re-invoke `/generate-release <VERSION>`.
```

Otherwise, proceed to Step 1.

## Step 1 — Sequence the release operations

Perform these four operations in order. The full per-step contract is in
`docs/llm/changelog.md#release-operations-version-bump-commit-tag-push`; the
summary below is the operational sequence.

### 1. CHANGELOG cut

Dispatch docs-writer to perform the cut in `CHANGELOG.md`:

- Rename the current `## [Unreleased]` heading to `## [<VERSION>] - <TODAY>`,
  where `<TODAY>` is today's date in `YYYY-MM-DD` form. Obtain it via
  `date -u +%Y-%m-%d` (UTC — for cross-timezone reproducibility).
- Insert a fresh, empty `## [Unreleased]` section above the dated heading.
- Preserve all existing entries and subsections under the now-dated heading.

If `date -u +%Y-%m-%d` fails, ABORT and tell the user to invoke the release
manually.

### 2. Version bump

Edit `pyproject.toml`: set `[project].version` to `<VERSION>`. Do not touch
any other field in that file.

### 3. Commit

- Run `git status` first.
- If `git status` shows "Unmerged paths" (equivalently,
  `git diff --name-only --diff-filter=U` returns non-empty), ABORT before
  staging: "Working tree has unmerged paths. Resolve conflicts and re-invoke
  `/generate-release <VERSION>`."
- Stage `CHANGELOG.md` and `pyproject.toml`.
- If the working tree has OTHER dirty files, include them ONLY if they look
  thematically part of this release (see "Best-effort decisions" below);
  otherwise leave them dirty.
- Commit with message `Release v<VERSION>`.

### 4. Tag + push

- If git tag `v<VERSION>` already exists (`git rev-parse -q --verify
  refs/tags/v<VERSION>` succeeds), ABORT before tagging — surface the
  conflict and do NOT force-overwrite an existing tag in subtask mode.
- Otherwise create an annotated tag: `git tag -a v<VERSION> -m "Release
  v<VERSION>"`.
- Push the tag: `git push origin v<VERSION>`.

## Best-effort decisions (state each one in the final report)

- **Dirty working tree beyond CHANGELOG + pyproject.** Include the extra
  files in the release commit ONLY if they look thematically part of the
  release; otherwise commit just `CHANGELOG.md` + `pyproject.toml` and leave
  the rest dirty. State which choice was made and why.
- **Tag already exists.** Abort before tagging (see Step 4). Never
  force-overwrite a tag without explicit user sign-off outside subtask mode.
- **`git push origin v<VERSION>` fails** (no remote, auth, network). Surface
  the error and leave the tag local — the user can push manually with
  `git push origin v<VERSION>`.
- **Date unobtainable.** If `date -u +%Y-%m-%d` fails (vanishingly rare on
  any Unix), abort and ask the user to invoke manually. UTC is used for
  cross-timezone reproducibility.
- **Other ambiguity.** Make the most reasonable choice, proceed, and state
  the assumption. Never block.

## Final report

Report all of the following in a concise summary:

- **Version released** (`<VERSION>`).
- **Commit hash** (short form from `git rev-parse --short HEAD`).
- **Tag name** (`v<VERSION>`).
- **Push status** (pushed / left local with reason).
- **Deviations and assumptions** — every best-effort decision made above,
  any files included or excluded from the commit, any skipped step.
