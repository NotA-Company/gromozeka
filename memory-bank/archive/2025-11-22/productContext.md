# Product Context

This file provides a high-level overview of the project and the expected product that will be created. Initially it is based upon projectBrief.md (if provided) and all other available project-related information in the working directory. This file is intended to be updated as the project evolves, and should be used to inform all other modes of the project's goals and context.
2025-09-07 14:37:27 - Initial Memory Bank setup for Gromozeka Telegram bot project

## Project Goal

Gromozeka is a Telegram bot written in Python. The project aims to create a functional Telegram bot with proper documentation, version control setup, and development workflow.

## Key Features

* Telegram bot functionality implemented in Python
* Proper project documentation and README
* Version control with appropriate .gitignore
* Structured development workflow with task reporting

## Overall Architecture

* Python-based Telegram bot with modular architecture
* Repository structure with key directories:
  - `internal/` - Core bot logic, database, services, and models
  - `lib/` - Reusable libraries (AI, markdown, weather, search, etc.)
  - `tests/` - Comprehensive test suites with e2e and integration tests
  - `configs/` - Configuration management with defaults and overrides
  - `docs/` - Documentation, design docs, and reports
  - `memory-bank/` - Project context and decision tracking
  - `scripts/` - Utility and helper scripts
* Task-based development approach with reporting templates
* Service-oriented architecture with dedicated services for caching, queuing, LLM management

## Technical Requirements

* Python 3.12+ required (uses StrEnum and other modern Python features)
* SQLite3 database
* libmagic library (5.46+)
* Memory bank system for tracking project context and decisions
[2025-10-26 14:04:00] - Updated Python version requirement to 3.12+
