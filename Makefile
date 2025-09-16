# Makefile for au-revoir-gitlab
# Copyright (c) 2025 Michele Tavella <meeghele@proton.me>

PYTHON := python3
PIP := pip
SCRIPT := au-revoir-gitlab.py

.PHONY: help install install-dev lint type-check format test test-unit test-cov clean check all validate

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	$(PIP) install -r requirements.txt

install-dev: ## Install development dependencies
	$(PIP) install -r requirements.txt
	@if [ -f requirements-dev.txt ]; then $(PIP) install -r requirements-dev.txt; fi

lint: ## Run linting with flake8 and pylint
	@echo "Running flake8..."
	flake8 $(SCRIPT)
	@echo "Running pylint..."
	pylint $(SCRIPT)

type-check: ## Run mypy type checking
	@echo "Running mypy type checking..."
	$(PYTHON) -m mypy $(SCRIPT)

format: ## Format code with black and isort
	@echo "Formatting with black..."
	black $(SCRIPT)
	@echo "Sorting imports with isort..."
	isort $(SCRIPT)

test: ## Run the script with --help to verify it works
	@echo "Testing script execution..."
	$(PYTHON) $(SCRIPT) --help > /dev/null && echo "Script executes successfully"

test-unit: ## Run unit tests (if present)
	@echo "Running unit tests..."
	@if [ -d tests ]; then $(PYTHON) -m pytest tests/ -v; else echo "(no tests/)"; fi

test-cov: ## Run unit tests with coverage report (if tests present)
	@echo "Running unit tests with coverage..."
	@if [ -d tests ]; then $(PYTHON) -m pytest tests/ --cov=$(SCRIPT) --cov-report=term-missing --cov-report=html; else echo "(no tests/)"; fi

clean: ## Clean up cache files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

check: lint type-check ## Run all code quality checks

all: install-dev format check test ## Install, format, check, and smoke test

validate: ## Validate the script can run (used by CI)
	$(PYTHON) $(SCRIPT) --help
