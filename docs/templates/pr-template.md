# Pull Request: [PR Title]

**Author:** [Developer Name]
**Date Created:** [YYYY-MM-DD]
**Target Branch:** [e.g., main, develop, master]
**Source Branch:** [e.g., feature/feature-name, fix/bug-name]

## Brief Description

[Provide a concise summary of the changes in 2-3 sentences. This description should be suitable for use in git commit messages and should clearly explain WHAT was changed and WHY. Focus on the business value or technical improvement delivered.]

**Key Change:** [One-sentence summary of the primary change]

**Commit Message Format:**
```
<type>(<scope>): <subject>

[Brief body describing what was implemented and why]

Closes: #issue-number (if applicable)
```

**How to fill this section:**
- Write a clear, action-oriented summary
- Explain the motivation behind the changes
- Mention any related issues or tickets
- Keep it concise but informative
- Use present tense (e.g., "Add feature" not "Added feature")
- `PR Title`, `Brief Description` and `Key change` sections should be doubled on Russian language

## Changed Files

[List all files that were modified, created, or deleted. This section should mirror the output of `git diff master --stat` or similar command. Include file paths and a brief description of changes for each file.]

**How to generate this section:**
```bash
# Run this command to get the file statistics:
git diff $(git merge-base master HEAD) --stat
```

### Files Modified
```git diff $(git merge-base master HEAD) --stat
path/to/file1.py                    | 45 +++++++++++++++++++++++++++++++++++++++++
path/to/file2.py                    | 23 +++++++++++++--------
path/to/file3.py                    | 12 +++++------
configs/config.toml                 |  5 +++--
4 files changed, 69 insertions(+), 16 deletions(-)
```

**Detailed Changes:**
- [`path/to/file1.py`](path/to/file1.py) - [Brief description of what changed and why]
- [`path/to/file2.py`](path/to/file2.py) - [Brief description of what changed and why]
- [`path/to/file3.py`](path/to/file3.py) - [Brief description of what changed and why]
- [`configs/config.toml`](configs/config.toml) - [Brief description of configuration changes]

### Files Created
- [`path/to/new/file1.py`](path/to/new/file1.py) - [Purpose and description]
- [`path/to/new/file2.py`](path/to/new/file2.py) - [Purpose and description]

### Files Deleted
- [`path/to/deleted/file.py`](path/to/deleted/file.py) - [Reason for deletion]

**How to fill this section:**
- Copy the output from `git diff $(git merge-base master HEAD) --stat`
- Add clickable file links for easy navigation
- Provide brief explanations for each significant change
- Group files by type of change (modified/created/deleted)
- Highlight any configuration or critical file changes

## Commit History

[List all commits included in this PR. This section should mirror the output of `git log master..HEAD --pretty=format:"%h - %an, %ar : %s"` or similar command. Each commit should be listed with its hash and message.]

**How to generate this section:**
```bash
# Run this command to get the commit list:
git log master..HEAD --pretty=format:"%h - %an, %ai : %s"
```

### Commits
```git log master..HEAD --pretty=format:"%h - %an, %ai : %s"
a1b2c3d feat(module): add new feature implementation
e4f5g6h fix(handler): resolve edge case in error handling
i7j8k9l docs(readme): update installation instructions
m0n1o2p test(module): add unit tests for new feature
q3r4s5t refactor(utils): improve code readability
```

**Commit Breakdown:**
1. **a1b2c3d** - `feat(module): add new feature implementation`
   - [Brief explanation of what this commit does]
   
2. **e4f5g6h** - `fix(handler): resolve edge case in error handling`
   - [Brief explanation of what this commit does]
   
3. **i7j8k9l** - `docs(readme): update installation instructions`
   - [Brief explanation of what this commit does]

[Continue for all commits...]

**How to fill this section:**
- Copy the output from `git log master..HEAD --pretty=format:"%h - %an, %ai : %s"`
- Optionally add brief explanations for complex commits
- Ensure commit messages follow conventional commit format
- Group related commits if there are many
- Highlight any commits that need special attention

## What Was Done

[Provide a comprehensive description of all changes, improvements, bug fixes, and other modifications included in this PR. Organize by category for clarity.]

### Features Added ✨
- **[Feature 1]:** [Detailed description of the feature]
  - **Implementation:** [How it was implemented]
  - **Benefits:** [Why this feature is valuable]
  - **Files:** [`file1.py`](path/to/file1.py), [`file2.py`](path/to/file2.py)

- **[Feature 2]:** [Detailed description of the feature]
  - **Implementation:** [How it was implemented]
  - **Benefits:** [Why this feature is valuable]
  - **Files:** [`file3.py`](path/to/file3.py)

### Bug Fixes 🐛
- **[Bug 1]:** [Description of the bug that was fixed]
  - **Root Cause:** [What caused the bug]
  - **Solution:** [How it was fixed]
  - **Impact:** [What this fix improves]
  - **Files:** [`file4.py`](path/to/file4.py)

- **[Bug 2]:** [Description of the bug that was fixed]
  - **Root Cause:** [What caused the bug]
  - **Solution:** [How it was fixed]
  - **Impact:** [What this fix improves]
  - **Files:** [`file5.py`](path/to/file5.py)

### Improvements 🚀
- **[Improvement 1]:** [Description of the improvement]
  - **Before:** [Previous state or behavior]
  - **After:** [New state or behavior]
  - **Benefit:** [Why this is better]
  - **Files:** [`file6.py`](path/to/file6.py)

- **[Improvement 2]:** [Description of the improvement]
  - **Before:** [Previous state or behavior]
  - **After:** [New state or behavior]
  - **Benefit:** [Why this is better]
  - **Files:** [`file7.py`](path/to/file7.py)

### Refactoring 🔧
- **[Refactoring 1]:** [Description of code refactoring]
  - **Motivation:** [Why this refactoring was needed]
  - **Changes:** [What was changed]
  - **Impact:** [How this improves the codebase]
  - **Files:** [`file8.py`](path/to/file8.py)

### Documentation 📝
- **[Documentation 1]:** [Description of documentation changes]
  - **Type:** [README, API docs, inline comments, etc.]
  - **Changes:** [What was documented or updated]
  - **Files:** [`README.md`](README.md), [`docs/api.md`](docs/api.md)

### Tests 🧪
- **[Test Suite 1]:** [Description of tests added or modified]
  - **Coverage:** [What is being tested]
  - **Type:** [Unit/Integration/E2E]
  - **Files:** [`test_file1.py`](tests/test_file1.py)

### Configuration Changes ⚙️
- **[Config Change 1]:** [Description of configuration changes]
  - **Setting:** [What was changed]
  - **Reason:** [Why this change was needed]
  - **Impact:** [How this affects the system]
  - **Files:** [`config.toml`](configs/config.toml)

**How to fill this section:**
- Organize changes by category (features, bugs, improvements, etc.)
- Use emojis for visual categorization (optional but helpful)
- Provide detailed explanations for each change
- Link to relevant files for each item
- Explain the "why" behind each change, not just the "what"
- Include before/after comparisons for improvements
- Mention any technical decisions or trade-offs made

## Testing Performed

[Put result of `make test` here]
```make test

...
internal/services/cache/test_cache_service.py .....................................                                                                        [100%]

====================================================================== slowest 4 durations =======================================================================
15.31s call     lib/yandex_search/test_performance.py::TestCachePerformance::testCacheMemoryUsage
10.38s call     lib/yandex_search/test_performance.py::TestMemoryAndResourceUsage::testMemoryCleanupAfterRequests
3.00s call     lib/openweathermap/test_dict_cache.py::test_dict_cache
2.50s call     lib/openweathermap/test_dict_cache.py::TestDictCacheAdvanced::test_cache_ttl_boundary_conditions
================================================================ 1330 passed in 67.48s (0:01:07) =================================================================

✅ All tests completed, dood!
```

**How to fill this section:**
- run `make test` and print the output to this section

## Additional Notes

[Any additional information that reviewers should know. This could include:]

- Known limitations or technical debt introduced
- Future improvements planned
- Alternative approaches considered
- Performance considerations
- Security considerations
- Dependencies on other PRs or external changes

**How to fill this section:**
- Add any context that doesn't fit in other sections
- Mention any trade-offs or compromises made
- Note any follow-up work needed
- Provide links to related discussions or documentation

---

**Review Guidelines for Reviewers:**

When reviewing this PR, please check:
- [ ] Code quality and adherence to project standards
- [ ] Test coverage is adequate
- [ ] Documentation is clear and complete
- [ ] No security vulnerabilities introduced
- [ ] Performance impact is acceptable
- [ ] Breaking changes are properly documented
- [ ] Deployment plan is clear and safe

---

## Template Usage Notes

**Instructions for using this template:**

1. **Replace ALL placeholder text** in brackets \[like this\] with actual content
2. **Fill out ALL sections** - do not leave any section empty or with placeholder text
3. **Generate file and commit lists** using the provided git commands
4. **Categorize changes** appropriately (features, bugs, improvements, etc.)
5. **Complete the checklist** before requesting review
6. **Link all files** using relative paths for easy navigation
7. **Follow commit message format** using conventional commits
8. **Delete all `How to fill this section` sections** after. Those sections are present to help filling template, they shouldn't be in repulting document
9. **Ensure no \[placeholders\] left** - ALL placeholders should be filled with actual content or deleted if no content needed

**Git Commands Reference:**

```bash
# Get list of changed files with statistics
git diff $(git merge-base master HEAD) --stat

# Get list of changed files with status (M=modified, A=added, D=deleted)
git diff $(git merge-base master HEAD) --name-status

# Get list of commits
git log master..HEAD --pretty=format:"%h - %an, %ai : %s"

# Get diff for specific file
git diff $(git merge-base master HEAD) -- path/to/file

# Check if branch is up to date with master
git fetch origin master
git log HEAD..origin/master --oneline
```

**Commit Message Format (Conventional Commits):**

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Best Practices:**

- Write clear, descriptive PR titles
- Keep PRs focused on a single concern when possible
- Break large changes into multiple PRs if feasible
- Respond to review comments promptly
- Update the PR description as changes are made
- Squash commits before merging if appropriate
- Delete branch after merging

**Status Indicators:**
- ✅ = Completed/Passed
- ⚠️ = Warning/Needs Attention
- ❌ = Failed/Not Completed
- 🔄 = In Progress