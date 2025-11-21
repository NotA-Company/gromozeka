# Product Context

[2025-11-21 22:48:35] - Condensed from archive to focus on current project essentials

## Project Goal

Gromozeka is a production-ready Telegram bot written in Python with comprehensive feature set and service-oriented architecture.

## Key Features

* Multi-platform bot support (Telegram and Max Messenger)
* Advanced LLM integration with multiple providers
* Comprehensive API integrations (Weather, Search, Geocoding)
* ML-powered spam detection with Bayes filter
* Golden data testing framework for reliable API testing
* Service layer with cache and queue services

## Overall Architecture

* **Core Structure**: Python 3.12+ with modular architecture
* **Bot Layer**: [`internal/bot/`](internal/bot/) - Multi-platform handlers and managers
* **Service Layer**: [`internal/services/`](internal/services/) - Cache and queue services
* **Library Layer**: [`lib/`](lib/) - Reusable components (AI, markdown, APIs, filters)
* **Testing**: [`tests/`](tests/) - Comprehensive test suites with golden data framework
* **Configuration**: [`configs/`](configs/) - TOML-based hierarchical configuration

## Technical Stack

* **Language**: Python 3.12+ (uses StrEnum and modern features)
* **Database**: SQLite with migration system
* **Configuration**: TOML format with environment overrides
* **Testing**: pytest with golden data testing
* **Quality**: Automated formatting (make format) and linting (make lint)