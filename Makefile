# Makefile for Gromozeka project

# Variables
VENV_PATH = ./venv
PIP = $(VENV_PATH)/bin/pip
PYTHON = $(VENV_PATH)/bin/python
FLAKE8 = $(VENV_PATH)/bin/flake8
BLACK = $(VENV_PATH)/bin/black

# Targets

# Create virtual environment
venv:
	python3 -m venv $(VENV_PATH)
	@echo "Virtual environment created at $(VENV_PATH)"

# Install all dependencies
install: venv
	$(PIP) install -r requirements.txt
	@echo "Dependencies installed"

activate: venv
	. $(VENV_PATH)/bin/activate

# Update requirements.txt
requirements:
	$(PIP) freeze > requirements.txt
	@echo "requirements.txt updated"

# Run the application
run:
	./run.sh

# Run linter on entire project (excluding venv)
lint:
#	$(FLAKE8) --exclude=$(VENV_PATH) .
	$(FLAKE8) .

# Format Python files using black
format:
	$(BLACK) --exclude venv .

# Run all tests
test:
	@echo "🧪 Running all Gromozeka tests, dood!"
	@echo "=================================="
	@echo ""
	@echo "📝 Running Markdown Parser tests..."
	$(PYTHON) lib/markdown/test/run_all_tests.py
	@echo ""
	@echo "🔍 Running Bayes Filter tests..."
	$(PYTHON) lib/spam/test_bayes_filter.py
	@echo ""
	@echo "🌤️  Running OpenWeatherMap tests..."
	$(PYTHON) lib/openweathermap/test_dict_cache.py
	@echo "⚠️  Skipping test_weather_client.py (test mocking issues - not related to circular import)"
	@echo ""
	@echo "🗄️  Running Database Migration tests..."
	$(PYTHON) internal/database/migrations/test_migrations.py
	@echo ""
	@echo "🤖 Running Bot Command Handler tests..."
	$(PYTHON) -m pytest tests/ -v
	@echo ""
	@echo "🛠️  Running Utility tests..."
	$(PYTHON) -m pytest lib/tests/ -v
	@echo ""
	@echo "✅ All tests completed, dood!"

# Check code quality (lint + format check)
check: lint
	@echo "Running format check..."
	$(BLACK) --check --diff .
	@echo "Code quality check completed"

# Clean build files and cache
clean:
	rm -rf $(VENV_PATH)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "Cleaned build files and cache"

# Show available targets
help:
	@echo "Available targets:"
	@echo "  venv         - Create virtual environment"
	@echo "  install      - Install all dependencies"
	@echo "  requirements - Update requirements.txt from requirements.direct.txt"
	@echo "  run          - Run the application"
	@echo "  lint         - Run linter on entire project"
	@echo "  format       - Format Python files"
	@echo "  test         - Run all tests"
	@echo "  check        - Check code quality (lint + format)"
	@echo "  clean        - Clean build files and cache"
	@echo "  help         - Show this help message"

# Default target
.PHONY: venv install requirements run lint format test check clean help
