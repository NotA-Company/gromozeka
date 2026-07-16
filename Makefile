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

# CI image used by .sourcecraft/ci.yaml (kept here so `make ci` stays in sync with it).
CI_IMAGE = docker.io/library/alpine:3.24

ifdef V
	ARGS := $(ARGS) -v
endif
# Targets

# Create virtual environment
# Note: this isn't .PHONY target
venv:
	python3 -m venv $(VENV_PATH)
	$(PIP) install --upgrade pip
	@echo "Virtual environment created at $(VENV_PATH)"

venv-alpine:
	python3 -m venv --system-site-packages $(VENV_PATH)
	$(PIP) install --upgrade pip
	@echo "Virtual environment created at $(VENV_PATH)"

# Install all dependencies
install: venv
	$(PIP) install -r requirements.txt
	@echo "Dependencies installed"

install-direct: venv
	$(PIP) install -r requirements.direct.txt
	@echo "Direct dependencies installed"

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
	@echo "Checking for circular imports..."
	$(PYTHON) -c "import main" || (echo "FAIL: circular import detected (or main.py cannot be imported)" && exit 1)
	$(PYRIGHT)

# Format Python files using black and isort
format: venv
	$(ISORT) .
	$(BLACK) .
	for dir in lib/ext_modules/*/; do \
		if [ -d "$$dir" -a "$$(basename "$$dir")" != "__pycache__" ]; then \
			$(ISORT) "$$dir"; \
			$(BLACK) "$$dir"; \
		fi; \
	done

# Run all tests
test: venv
	@echo "🧪 Running all Gromozeka tests, dood!"
	@echo "=================================="
	@echo ""
	time timeout 5m $(PYTEST) --durations=4 $(ARGS)
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

# Check that local markdown links resolve to files on disk
check-docs: venv
	$(PYTHON) scripts/check_docs.py

# Run the full CI pipeline locally inside the SAME Alpine container CI uses.
# The in-container script (apk deps -> venv-alpine -> install -> packaging fix
# -> check -> test) lives in scripts/ci.sh and is the SINGLE SOURCE OF TRUTH
# shared with .sourcecraft/ci.yaml, so the two runners cannot drift apart.
#
# The repo is copied into the container from a read-only bind mount, so the host
# ./venv is never touched: the container builds its own ./venv (Alpine/musl) in
# its writable layer and discards it on exit (--rm). apk + pip install run fresh
# every time (no cross-run caching), mirroring sourcecraft's clean-container run.
ci:
	docker run --rm \
		-v "$(CURDIR):/src:ro" \
		$(CI_IMAGE) \
		sh -c '\
			set -eo pipefail && \
			apk add --no-cache git && \
			mkdir -p /app && \
			tar -C /src -cf - --exclude=./venv --exclude=./.git --exclude="./.env*" --exclude="*/__pycache__" --exclude="./lib/ext_modules/*" . | tar -C /app -xf - && \
			rm -rf /app/venv && \
			cd /app && \
			git init . && \
			git config --global --add safe.directory /app && \
			sh scripts/ci.sh'
	@echo "✅ CI pipeline completed, dood!"

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
	@echo "  venv-alpine                 - Create virtual environment for Alpine Linux (with --system-site-packages to have access to global py3-onnxruntime)"
	@echo "  install                     - Install all dependencies (from frozen snapshot)"
	@echo "  install-direct              - Install all dependencies (from direct dependencies file)"
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
	@echo "  check-docs                  - Check that local markdown links resolve"
	@echo "  ci                          - Run the full CI pipeline locally in the Alpine container (mirrors .sourcecraft/ci.yaml); needs Docker"
	@echo "  clean                       - Clean build files and cache"
	@echo "  help                        - Show this help message"

# Default target
.PHONY: install activate freeze-requirements list-outdated-requirements run lint format test test-failed coverage check check-docs ci clean help venv-alpine

