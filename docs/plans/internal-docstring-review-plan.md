# Internal Directory Docstring Review Implementation Plan

## Task Overview

Comprehensively review all files in `/internal` directory for missing or incorrect docstrings and fix them. This follows the successful completion of docstring fixes for `/lib/max_bot` (87 docstrings fixed).

## Scope

**Target Directory**: `/internal/` and all subdirectories
**Focus Areas**:
- `/internal/bot/` - Bot application implementations
- `/internal/services/` - Service layer (cache, LLM, queue)
- `/internal/database/` - Database models and operations
- `/internal/models/` - Internal data models

**Exclusions**: Test files (files starting with `test_` or in test directories)

## Requirements

- Keep docstrings compact and concise (following project rules)
- Always describe all arguments and return types
- Use proper Python docstring format (triple quotes)
- Follow camelCase naming convention for parameters in docstrings
- Ensure all public classes, methods, and functions have docstrings
- Private methods (starting with _) should have docstrings if their purpose isn't obvious

## Implementation Strategy

### Phase 1: Discovery and Planning
1. **Code Definition Analysis**: Use `list_code_definition_names` to get overview of all classes, functions, and methods
2. **File Inventory**: Create systematic list of all Python files to review
3. **Priority Assessment**: Identify files with most missing docstrings

### Phase 2: Systematic Review by Subdirectory
1. **Bot Layer** (`/internal/bot/`):
   - Application implementations (telegram/, max/)
   - Common handlers and utilities
   - Models and shared components

2. **Service Layer** (`/internal/services/`):
   - Cache service implementation
   - LLM service integration
   - Queue service components

3. **Database Layer** (`/internal/database/`):
   - Database models and TypedDict definitions
   - Migration system components
   - Database wrapper and manager

4. **Models Layer** (`/internal/models/`):
   - Internal data models
   - Shared type definitions

### Phase 3: Quality Assurance
1. **Code Quality**: Run `make format lint` after each batch of changes
2. **Testing**: Run `make test` to ensure no functionality breaks
3. **Documentation**: Track changes and create comprehensive report

## Review Checklist for Each File

### Module Level
- [ ] Module docstring exists and describes purpose
- [ ] Module docstring is concise but informative

### Classes
- [ ] Class docstring exists for all public classes
- [ ] Class docstring describes purpose and key attributes
- [ ] Private classes have docstrings if purpose isn't obvious

### Functions/Methods
- [ ] All public functions/methods have docstrings
- [ ] Docstrings include Args section with all parameters
- [ ] Docstrings include Returns section with return type
- [ ] Private methods have docstrings if purpose isn't obvious
- [ ] Parameter names in docstrings use camelCase

### Docstring Quality
- [ ] Descriptions are concise but complete
- [ ] No TODO comments for missing docstrings
- [ ] Proper triple-quote format
- [ ] Consistent style with project conventions

## Tracking and Reporting

### Progress Metrics
- Files reviewed: X/Y total files
- Docstrings added/fixed: X total
- Files with most changes: [list]
- Common patterns identified: [list]

### Final Report
Create comprehensive report at `docs/reports/internal-docstring-completion-report.md` including:
- Summary of all changes made
- Statistics by subdirectory
- Patterns and issues discovered
- Recommendations for future maintenance

## Success Criteria

1. **Completeness**: All public classes, functions, and methods have proper docstrings
2. **Quality**: All docstrings follow project conventions and are informative
3. **Consistency**: Uniform style across all files in `/internal` directory
4. **Functionality**: All tests pass after changes
5. **Code Quality**: No linting issues after changes

## Timeline Estimate

- **Phase 1**: 1-2 hours (discovery and planning)
- **Phase 2**: 6-10 hours (systematic review and fixes)
- **Phase 3**: 1-2 hours (quality assurance and reporting)

**Total Estimated Time**: 8-14 hours

## Dependencies

- Access to all files in `/internal` directory
- Ability to run `make format`, `make lint`, and `make test`
- Memory Bank access for progress tracking
- Report template at `docs/templates/task-report-template.md`