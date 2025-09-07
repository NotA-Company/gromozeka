# System Patterns *Optional*

This file documents recurring patterns and standards used in the project.
It is optional, but recommended to be updated as the project evolves.
2025-09-07 14:38:22 - Initial Memory Bank setup and pattern documentation initialization.

## Coding Patterns

* Python-based development for Telegram bot functionality
* Task-based development workflow with structured reporting
* Template-driven documentation approach
* Memory Bank system for context and decision tracking

## Architectural Patterns

* Repository structure with organized directories (docs/, memory-bank/, .roo/)
* Separation of concerns: templates, reports, plans, and memory tracking
* Version control integration with appropriate .gitignore patterns
* Documentation-first approach with README and structured reporting

## Testing Patterns

* To be established as project develops
* Will likely include unit tests for bot functionality
* Integration tests for Telegram API interactions
* Manual validation procedures for bot behavior

## Task Completion Workflow

2025-09-07 14:43:52 - Added mandatory task reporting pattern

* **Task Report Requirement:** After completing any task, dood should create a task report using the template at `docs/templates/task-report-template.md`
* **Report Location:** All task reports should be saved in `docs/reports/` directory with naming pattern `task-[X.Y.Z]-completion-report.md`
* **Report Content:** Must include all sections from template with actual project-specific information, no placeholder text
* **Memory Bank Update:** Task completion should trigger Memory Bank updates to reflect progress and decisions made