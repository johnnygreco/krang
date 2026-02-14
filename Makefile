.DEFAULT_GOAL := help
.PHONY: help install install-hooks test lint format coverage clean publish

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (including dev extras)
	uv sync --extra dev

install-hooks: ## Install pre-commit hooks (run after install)
	uv run pre-commit install

test: ## Run tests with verbose output
	uv run pytest tests/ -v

lint: ## Auto-fix lint issues and type-check
	uv run ruff format src/ tests/
	uv run ruff check src/ tests/ --fix --unsafe-fixes
	uv run ty check src/kraang/

format: ## Auto-format and fix lint issues
	uv run ruff format src/ tests/
	uv run ruff check src/ tests/ --fix --unsafe-fixes

coverage: ## Run tests with coverage report
	uv run coverage run -m pytest tests/ -v
	uv run coverage report -m
	uv run coverage html

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

publish: ## Publish a release (usage: make publish VERSION=x.y.z)
	./scripts/publish.sh $(VERSION)
