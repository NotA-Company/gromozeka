# Documentation Review Process

> **Purpose**: Establish a systematic, repeatable process for reviewing and maintaining Gromozeka documentation to ensure accuracy, consistency, and alignment with the codebase.
>
> **Audience**: Developers, maintainers, and contributors who need to review, update, or create documentation.
>
> **Last Updated**: 2026-05-08
>
> **Context**: This document codifies the process used during the comprehensive documentation review on 2026-05-08 that analyzed 80 files, archived 35 outdated files, and consolidated 67+ TODO items.

---

## Table of Contents

1. [When to Review Documentation](#when-to-review-documentation)
2. [Review Process Step-by-Step](#review-process-step-by-step)
3. [Reviewer Checklist](#reviewer-checklist)
4. [Archival Criteria](#archival-criteria)
5. [TODO Extraction and Consolidation](#todo-extraction-and-consolidation)
6. [Quality Gates](#quality-gates)
7. [Examples from the 2026-05-08 Review](#examples-from-the-2026-05-08-review)
8. [Maintenance Recommendations](#maintenance-recommendations)

---

## When to Review Documentation

### Scheduled Reviews

- **Quarterly reviews recommended**: Conduct comprehensive reviews every 3 months to catch drift, outdated information, and accumulated TODO items.
- **Before major releases**: Review all documentation relevant to the release scope to ensure accuracy before shipping.

### Event-Driven Reviews

- **After major refactoring or architectural changes**: Review any documentation that describes changed architecture, patterns, or implementation details.
- **When adding new subsystems or features**: Ensure new functionality is documented and related docs reference it appropriately.
- **When changing hard rules or conventions**: Update `AGENTS.md` and any cross-references immediately.
- **After database schema changes**: Update `docs/database-schema.md` and `docs/database-schema-llm.md` to reflect current structure.

### Red Flags That Trigger Reviews

- Outdated examples or code snippets
- Contradictory information between documents
- Missing or broken references
- TODO comments older than 3 months
- Code changes without corresponding documentation updates

---

## Review Process Step-by-Step

### Phase 1: Planning and Scoping

1. **Define review scope**
   ```bash
   # Use the `explore` agent to find all relevant documentation files
   # Example: "Find all docs mentioning handlers, database, and configuration"
   ```

2. **Identify reviewers**
   - Assign primary reviewer for each document section
   - Include subject matter experts for technical areas
   - Schedule review timeline (recommend 1-2 weeks for comprehensive reviews)

3. **Create review checklist**
   - Use the [Reviewer Checklist](#reviewer-checklist) below as a starting point
   - Add checklist items specific to your review scope

### Phase 2: Discovery and Analysis

1. **Inventory all documentation files**
   ```bash
   # Find all markdown documentation
   find docs -name "*.md" -type f

   # Find all AI guide files
   find docs/llm -name "*.md" -type f
   ```

2. **Map relationships between documents**
   - Identify cross-references and links
   - Note which documents are authoritative sources vs. duplicates
   - Diagram the documentation hierarchy if needed

3. **Analyze each document systematically**
   - Read each file completely
   - Extract findings (outdated info, inconsistencies, TODOs)
   - Link findings to source files and line numbers

4. **Extract TODOs and action items**
   - Search for "TODO", "FIXME", "XXX" comments
   - Identify outdated recommendations
   - Capture suggested improvements

### Phase 3: Synthesis and Consolidation

1. **Consolidate TODOs**
   - Group similar items together
   - Remove duplicates
   - Prioritize using CRITICAL/HIGH/MEDIUM/LOW framework
   - Link each TODO to its source document

2. **Identify archival candidates**
   - Use the [Archival Criteria](#archival-criteria) below
   - Create index of files to archive
   - Ensure no critical information is lost

3. **Create action plan**
   - Document what needs to be updated
   - Estimate effort for each item
   - Assign owners and due dates
   - Create pull requests or issues for tracking

### Phase 4: Execution and Updates

1. **Apply changes to documentation**
   ```
   For each document update:
   1. Read the file first (required by edit tool)
   2. Apply targeted edits using the edit tool
   3. Run `make format lint test` after changes
   4. Verify links and cross-references
   5. Update related documents
   ```

2. **Archive outdated documents**
   ```bash
   # Create archive directory structure
   mkdir -p docs/archive/review-YYYY-MM-DD

   # Move files with descriptive suffix
   mv docs/old-doc.md docs/archive/review-YYYY-MM-DD/old-doc.md

   # Update AGENTS.md to remove archived references
   ```

3. **Update central TODO tracking**
   - Consolidate findings into `docs/TODO.md`
   - Organize by priority (CRITICAL/HIGH/MEDIUM/LOW)
   - Include source references and metadata
   - Track completion status

### Phase 5: Verification and Follow-up

1. **Complete quality gates**
   - Run `make format lint test` (see [Quality Gates](#quality-gates))
   - Verify all links work
   - Check for broken cross-references
   - Ensure code examples are accurate

2. **Update `update-project-docs` skill**
   - If documentation structure changed significantly
   - If new document types were added
   - If reference patterns changed

3. **Schedule follow-up reviews**
   - Set calendar reminders for next quarterly review
   - Track newly added TODOs between reviews
   - Monitor for documentation drift

---

## Reviewer Checklist

### Document Structure and Organization

- [ ] Document has clear title, audience, and last updated date
- [ ] Table of contents exists and is accurate (for longer docs)
- [ ] Sections are logically organized and easy to navigate
- [ ] Related documents are referenced in "See Also" or similar section
- [ ] Document lives in appropriate location (docs/ vs docs/llm/ vs docs/reports/)

### Content and Accuracy

- [ ] All code examples are accurate and current
- [ ] Code follows project conventions (camelCase, docstrings, type hints)
- [ ] File paths and line numbers are correct
- [ ] Architecture descriptions match actual implementation
- [ ] Configuration examples are valid and complete
- [ ] SQL examples follow portability rules (no AUTOINCREMENT, use provider methods)

### Consistency and Cross-References

- [ ] References to AGENTS.md rules are accurate
- [ ] Links to other docs resolve correctly
- [ ] Naming conventions are consistent with codebase
- [ ] No contradictory information between documents
- [ ] API signatures match actual implementation

### Completeness

- [ ] All key concepts are explained
- [ ] Examples cover common use cases
- [ ] Edge cases are documented where relevant
- [ ] Security considerations are included where applicable
- [ ] Performance considerations noted when significant

### Accessibility and Usability

- [ ] Language is clear and concise
- [ ] Technical jargon is explained or linked
- [ ] Examples are practical and runnable
- [ ] Diagrams/charts are readable (if present)
- [ ] Document is at appropriate depth for target audience

### AGENTS.md Compliance

- [ ] Follows camelCase naming convention in all code examples
- [ ] Uses `./venv/bin/python3` for Python commands
- [ ] References `make format lint test` workflow
- [ ] Mentions `update-project-docs` skill for post-change updates
- [ ] Follows project import organization rules
- [ ] Avoids pydantic in examples (uses raw dicts + TypedDict)

### Action Items and TODOs

- [ ] TODO comments are extracted and tracked
- [ ] Outdated recommendations are removed or updated
- [ ] Suggestions are actionable with effort estimates
- [ ] Priority levels are assigned (CRITICAL/HIGH/MEDIUM/LOW)
- [ ] Source references are included (file:line or doc name)

### Code Quality Integration

- [ ] Documentation mentions `make format lint` before and after edits
- [ ] Documentation includes `make test` for verification
- [ ] Instructions use project's actual commands (from Makefile)
- [ ] Emphasizes type hints and docstrings requirements

---

## Archival Criteria

### Archive Documents When:

**Outdated Implementation Details**
- Documents describe functionality that no longer exists
- Code examples reference deleted files or refactored structures
- Architecture diagrams don't match current implementation
- Database schema references removed tables or columns

**Superseded by Better Documentation**
- Information exists in more canonical/authoritative location
- Better organized document covers the same ground
- Document duplicates content elsewhere
- Content merged into larger, more comprehensive doc

**Historical Context No Longer Relevant**
- Design discussions for completed features
- Temporary/workaround instructions that are no longer needed
- Beta/experimental feature docs for now-stable features
- Migration guides for versions no longer in use

**Experimental/Abandoned Features**
- Documents for features that were removed or never completed
- Proof-of-concept implementations that didn't ship
- Experimental APIs that were changed or removed

### Keep Documents When:

**Architectural Decisions (ADRs)**
- Design decisions that explain "why" something is built a certain way
- Trade-offs and alternatives considered
- Historical context for future maintainers
- Located in `docs/reports/` with clear dates

**Living Reference Documentation**
- `AGENTS.md` - Hard rules and conventions
- `docs/llm/*.md` - Canonical LLM agent guides
- `docs/developer-guide.md` - Human-readable project documentation
- `docs/database-schema*.md` - Current database structure
- `README*.md` - User-facing documentation

**Working Examples and Templates**
- Template files for new features
- Working examples that demonstrate patterns
- Test fixtures and golden data documentation
- Configuration examples

### Archival Process

When archiving documents:

1. **Create archival directory**
   ```bash
   mkdir -p docs/archive/review-YYYY-MM-DD
   ```

2. **Move with context**
   ```bash
   # Rename with descriptive suffix indicating why archived
   mv docs/old-feature.md docs/archive/review-2026-05-08/old-feature-removed-in-v1.5.md
   ```

3. **Create archive index**
   ```bash
   # Create docs/archive/review-2026-05-08/INDEX.md
   # List all archived files with reasons
   ```

4. **Update cross-references**
   - Remove broken links from active docs
   - Update AGENTS.md if archived docs were listed there
   - Add "See also" references to archival backup if needed for historical research

5. **Preserve critical information**
   - Migrate valuable content to active docs before archiving
   - Extract TODOs and action items to `docs/TODO.md`
   - Record architectural decisions in ADR format

---

## TODO Extraction and Consolidation

### Extraction Process

1. **Search systematically for TODOs**
   ```bash
   # Find TODO comments in code
   rg "TODO|FIXME|XXX" --type py -n

   # Find TODO sections in documentation
   rg -i "todo|note|improvement" docs/ --type md -n
   ```

2. **For each TODO, capture:**
   - Description of the item
   - Priority (CRITICAL/HIGH/MEDIUM/LOW)
   - Source location (file:line or document:section)
   - Estimated effort (when clear from context)
   - Type (bug fix, feature, refactor, documentation)
   - Dependencies or prerequisites

3. **Categorize by priority**
   - **CRITICAL**: Breaks functionality, security issues, violates hard rules
   - **HIGH**: Major features, reliability issues, performance problems
   - **MEDIUM**: Documentation updates, consistency fixes, code quality
   - **LOW**: Nice-to-have, optimizations, backlog items

### Consolidation Format

Consolidated TODOs should be saved in `docs/TODO.md` using this structure:

```markdown
# Documentation TODOs

Generated from documentation review on YYYY-MM-DD

## CRITICAL Priority

### Category
1. **Brief description** - Detailed explanation with context (Estimated: X hours)
   - Source: `path/to/file:line` or `document-name`

## HIGH Priority

### Category
2. **Brief description** - Detailed explanation (Estimated: X days)
   - Source: `path/to/document-section`

## MEDIUM Priority

### Category
3. **Brief description** - Explanation (Status: ✅ IMPLEMENTED)
   - Source: reference

## LOW Priority

### Category
4. **Brief description** - Explanation
   - Source: reference

## Total Count

- **CRITICAL**: N items
- **HIGH**: N items
- **MEDIUM**: N items
- **LOW**: N items
- **Total**: N actionable items
```

### Example from 2026-05-08 Review

The review generated 64+ actionable items organized in `docs/TODO.md`:

```markdown
## CRITICAL Priority

### Migration Examples and Doc Updates
1. **Update migration examples in `docs/llm/database.md`** - The doc shows stale sync pattern `def up(self, cursor)` instead of `async def up(self, sqlProvider: BaseSQLProvider)`. Also contains `AUTOINCREMENT` examples that contradict AGENTS.md. (Estimated: 2-3 hours)
   - Source: `docs/reports/pr-26.05.06-divination-handler.md` D-2
```

### Deduplication Strategy

- **Exact duplicates**: Keep one, note which sources had it
- **Related items**: Group together under parent item
- **Implementation vs. documentation**: Separate TODOs from follow-up documentation updates
- **Completed items**: Mark with `✅ IMPLEMENTED` or remove from active list
- WONTFIX items**: Document why with "Status: ✅ IMPLEMENTED (update docs only)" or similar

---

## Quality Gates

### Pre-Push Verification

Before committing documentation changes:

```bash
# Step 1: Format and lint
make format lint

# Step 2: Run tests
make test

# Step 3: Verify no broken links (optional but recommended)
# Use markdown-link-check or similar tool if available
```

### Documentation-Specific Checks

- [ ] All code examples follow project conventions (camelCase, type hints, docstrings)
- [ ] All code uses `./venv/bin/python3` (not `python` or `python3`)
- [ ] All mentions of commands match actual Makefile targets
- [ ] All file paths exist and are accurate
- [ ] No hardcoded tokens, secrets, or credentials
- [ ] Cross-references resolve and are appropriate
- [ ] Document includes last updated date and context
- [ ] `update-project-docs` skill used for behavior/schema/config changes

### Integration Tests for Documentation

For documentation that describes workflows or processes:

```bash
# Follow the documented steps literally
# Example: If doc says "run these commands to create a handler", run them

# Verify expected outcomes
# - Handler exists
# - Code compiles
# - Tests pass

# Update doc if steps fail or produce different results
```

### AGENTS.md Validation

Ensure documentation adheres to AGENTS.md hard rules:

- **Naming**: Verify all code examples use camelCase for variables/functions, PascalCase for classes
- **Docstrings**: Check all function examples include `Args:` and `Returns:` sections
- **Type hints**: Ensure all function params and returns have types
- **Python execution**: All Python commands use `./venv/bin/python3`
- **Import organization**: No inside-function imports unless documented as exception
- **No pydantic**: Examples use raw dicts + TypedDict + hand-typed classes
- **SQL portability**: Database examples use provider methods, not raw sqlite3
- **Workflow**: Documentation includes `make format lint test` sequence

---

## Examples from the 2026-05-08 Review

### Example 1: Code Example Update

**Finding**: Migration examples in `docs/llm/database.md` showed outdated pattern

```python
# OLD (incorrect):
def up(self, cursor):
    cursor.execute("CREATE TABLE ...")
```

**Updated to**:
```python
# NEW (correct):
async def up(self, sqlProvider: BaseSQLProvider) -> None:
    await sqlProvider.execute("CREATE TABLE ...")
```

**Lesson**: Always verify code examples against actual implementation. The migration API changed from synchronous cursors to async providers.

### Example 2: Archival Decision

**Documentation**: Multiple PR review reports in `docs/reports/`

**Decision**: Archive reports older than 2 months to `docs/archive/review-2026-05-08/`

**Rationale**:
- Reports contained historical context already captured in code
- Maintainers can refer to git history for PR details
- Active TODOs extracted to `docs/TODO.md` before archiving
- Archive location and index allow research if needed

**Lesson**: Maintain archival index with reasons for future reference.

### Example 3: TODO Consolidation

**Finding**: 67+ TODO items scattered across 15 parallel analysis tasks

**Action**: Consolidated into single `docs/TODO.md` with:
- Priority levels (CRITICAL/HIGH/MEDIUM/LOW)
- Source references for each item
- Effort estimates where available
- Status tracking for completed items

**Result**: 64 actionable items organized by priority with clear lineage to review sources

**Lesson**: Extract and prioritize findings immediately while context is fresh. Use standardized format for maintainability.

### Example 4: Cross-Reference Updates

**Finding**: `AGENTS.md` referenced `DatabaseWrapper` class that no longer exists

**Action**: Updated all references to use `Database` class and repository pattern

**Files updated**:
- `AGENTS.md`
- `docs/llm/database.md`
- `docs/suggestions/improvements.md`
- Any other documentation referencing the old wrapper

**Lesson**: Search for cross-references when renaming or removing major components.

### Example 5: Documentation Workflow Discovery

**Finding**: Team was running `make format lint` but not `make test` after doc changes

**Action**: Updated all documentation to emphasize `make format lint test` sequence

**Standard now**:
```bash
# Step 1: Before making changes
make format lint

# Step 2: After making changes
make format lint

# Step 3: Final verification
make test
```

**Lesson**: Documentation is code and should be tested like code. Examples must work.

---

## Maintenance Recommendations

### Ongoing Maintenance Practices

1. **Update docs with code changes**
   - Always load the `update-project-docs` skill after code changes
   - Update relevant docs immediately, not "later"
   - Run `make format lint test` before committing doc updates

2. **Use the `update-project-docs` skill**
   ```
   When to use:
   - After implementing a feature
   - After fixing a bug
   - After refactoring
   - After adding a handler/service/library
   - After changing database schema
   - After modifying configuration
   
   The skill provides decision matrix mapping change types
   to specific documentation sections.
   ```

3. **Track TODOs continuously**
   - When documenting new code, create TODOs for missing documentation
   - Tag TODOs with priority in comments
   - Consolidate into `docs/TODO.md` during regular reviews

4. **Review cross-references regularly**
   - When renaming files, search for references: `git grep -w "OldName"`
   - After large refactors, verify all docs still accurate
   - Update AGENTS.md when conventions change

5. **Maintain separation of concerns**
   - `docs/llm/*.md`: LLM agent guides (technical, authoritative)
   - `docs/developer-guide.md`: Human-readable documentation
   - `docs/reports/`: ADRs, design discussions, temporary analysis
   - `docs/archive/`: Historical backup, read-only
   - `docs/TODO.md`: Consolidated action items

### Automation Opportunities

1. **Automated link checking**
   ```bash
   # Add to CI pipeline (recommended)
   # Find broken markdown links
   markdown-link-check docs/**/*.md
   ```

2. **Code example extraction**
   ```bash
   # Extract code blocks for syntax validation
   # Run extracted Python through linter
   ```

3. **TODO gathering**
   ```bash
   # Periodically gather TODOs from code
   rg "TODO|FIXME" --type py -A 2 > TODO-extraction.txt
   ```

4. **Documentation coverage tracking**
   ```bash
   # Find undocumented public functions
   # Check for missing docstrings in handlers/services
   ```

### Team Workflow Integration

1. **Include documentation in code review**
   - PR reviewers check if docs need updating
   - Add "documentation:" label to PRs that touch docs
   - Require doc updates for behavioral changes

2. **Documentation-first for new features**
   - Write docs alongside code, not after
   - Use docs as specification for review
   - Verify docs accurately describe implementation

3. **Documentation retrospectives**
   - After major releases, review what docs were missing
   - Identify patterns of documentation debt
   - Update templates and checklists to prevent recurrence

4. **Onboarding using docs**
   - New contributors read `AGENTS.md` and `docs/llm/index.md` first
   - Use documentation review as learning exercise for new team members
   - Encourage documentation improvements from all contributors

### Metrics and Monitoring

Track these metrics to gauge documentation health:

- **Age of last comprehensive review**: Target < 6 months
- **Number of stale TODO items**: Target decreasing trend
- **Code examples coverage**: Percentage of public APIs with examples
- **Link rot rate**: Number of broken cross-references
- **Documentation PR frequency**: How often docs are updated

---

## Quick Reference: Review Commands

```bash
# Find all documentation
find docs -name "*.md" -type f

# Find LLM agent guide files
find docs/llm -name "*.md" -type f

# Search for TODOs in code
rg "TODO|FIXME|XXX" --type py -n

# Search for TODOs in documentation
rg -i "todo|note|improvement" docs/ --type md -n

# Check for broken links (requires markdown-link-check)
markdown-link-check docs/**/*.md

# Verify Python code examples compile
# Extract Python blocks and run through venv/bin/python3 -m py_compile

# Check formatting
make format lint

# Run tests
make test

# Find next migration version
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1

# Search for cross-references before archiving
git grep -w "old-file-name" docs/
```

---

## Appendices

### Appendix A: Review Template

```markdown
# Documentation Review: [Title]

**Date**: YYYY-MM-DD
**Scope**: [Description of what was reviewed]
**Reviewer**: [Name]
**Team**: [Names of contributors]

## Summary

[High-level overview of findings]

## Files Reviewed

- List of all files analyzed

## Key Findings

- Major issues discovered
- Outdated sections identified
- TODOs extracted

## Actions Taken

- Documents archived
- Documents updated
- TODOs consolidated

## Recommendations

- Process improvements
- Tooling suggestions
- Training needs

## TODOs Extracted

[Consolidated TODOs with priorities]

## Open Questions

- Items requiring clarification
- Decisions pending

---

**Total items**: [count]
**Completed**: [count]
**In progress**: [count]
**Deferred**: [count]
```

### Appendix B: Related Documentation

- [`AGENTS.md`](../AGENTS.md) — Project hard rules and conventions
- [`docs/llm/index.md`](llm/index.md) — LLM agent guide index
- [`update-project-docs` skill](../.agents/skills/update-project-docs/SKILL.md) — Post-change documentation workflow
- [`docs/TODO.md`](TODO.md) — Consolidated action items from reviews

### Appendix C: Glossary

- **ADR**: Architecture Decision Record - Formal record of significant architectural decisions
- **Golden data**: Pre-recorded API responses for deterministic testing
- **LLM**: Large Language Model - AI text generation systems
- **Repository**: Data access object implementing repository pattern
- **Singleton**: Class with only one instance per application (via `getInstance()`)
- **Tier**: Chat access level (free/paid/bot_owner) with different feature sets

---

**Document Version**: 1.0
**Created**: 2026-05-08
**Last Updated**: 2026-05-08
**Review Cycle**: Recommended quarterly or after major changes
