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

# Update requirements.txt
requirements:
	$(PIP) freeze > requirements.txt
	@echo "requirements.txt updated"

# Run the application
run:
	./run.sh

# Run linter on entire project (excluding venv)
lint:
	$(FLAKE8) --exclude=$(VENV_PATH) .

# Format Python files using black
format:
	$(PYTHON) scripts/format_python.py

# Run all tests
test:
	$(PYTHON) -m pytest lib/tests/ lib/markdown/test/
	./lib/markdown/tests/run_tests.sh
	@echo "All tests completed"

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
