# Makefile for Gromozeka project

# Variables
VENV_PATH = ./venv
PIP = $(VENV_PATH)/bin/pip
PYTHON = $(VENV_PATH)/bin/python
FLAKE8 = $(VENV_PATH)/bin/flake8
BLACK = $(VENV_PATH)/bin/black
ISORT = $(VENV_PATH)/bin/isort
PYRIGHT = $(VENV_PATH)/bin/pyright
PYTEST = $(VENV_PATH)/bin/pytest

ifdef V
	ARGS := $(ARGS) -v
endif
# Targets

# Create virtual environment
# Note: this isn't .PHONY target
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
freeze-requirements: venv
	$(PIP) freeze > requirements.txt
	@echo "requirements.txt updated"

list-outdated-requirements: venv
	@echo "List of outdated requirements"
	$(PIP) list --outdated
	
# Run the application
run: venv
	./run.sh

# Run linter on entire project
lint: venv
	$(FLAKE8) .
	$(ISORT) --check-only --diff .
	$(PYRIGHT)

# Format Python files using black and isort
format: venv
	$(ISORT) .
	$(BLACK) .

# Run all tests
test: venv
	@echo "🧪 Running all Gromozeka tests, dood!"
	@echo "=================================="
	@echo ""
	$(PYTEST) --durations=4 $(ARGS)
	@echo ""
	@echo "✅ All tests completed, dood!"

test-failed: venv
	@echo "🧪 Re-Running Failed Gromozeka tests, dood!"
	@echo "=================================="
	@echo ""
	$(PYTEST) --last-failed --durations=4 $(ARGS)
	@echo ""
	@echo "✅ Tests completed, dood!"

# Run tests with coverage report
coverage: venv
	@echo "📊 Running tests with coverage report, dood!"
	@echo "============================================"
	@echo ""
	$(PYTEST) --cov=. --cov-report=term-missing --cov-report=html --cov-branch $(ARGS)
	@echo ""
	@echo "✅ Coverage report generated, dood!"
	@echo "📁 HTML report available at: htmlcov/index.html"

# Check code quality (lint + format check)
check: lint
	@echo "Running format check..."
	$(BLACK) --check --diff .
	@echo "Code quality check completed"

# Clean build files and cache
clean:
	rm -rf $(VENV_PATH)
	find . -type d -name "__pycache__" -exec rm -rf '{}' +
	find . -type f -name "*.pyc" -delete
	@echo "Cleaned build files and cache"

# Show available targets
help:
	@echo "Available targets:"
	@echo "  venv                        - Create virtual environment"
	@echo "  install                     - Install all dependencies"
	@echo "  activate                    - Activate virtual environment"
	@echo "  freeze-requirements         - Update requirements.txt with current packages"
	@echo "  list-outdated-requirements  - List outdated packages"
	@echo "  run                         - Run the application"
	@echo "  lint                        - Run linter on entire project"
	@echo "  format                      - Format Python files with black and isort"
	@echo "  test                        - Run all tests (Pass V=1 for verbose output)"
	@echo "  test-failed                 - Re-run failed tests (Pass V=1 for verbose output)"
	@echo "  coverage                    - Run tests with coverage report (Pass V=1 for verbose output)"
	@echo "  check                       - Check code quality (lint + format)"
	@echo "  clean                       - Clean build files and cache"
	@echo "  help                        - Show this help message"

# Default target
.PHONY: install activate freeze-requirements list-outdated-requirements run lint format test test-failed coverage check clean help
