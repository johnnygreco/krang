.PHONY: install test lint format coverage clean publish

install:
	uv sync --extra dev

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/
	uv run mypy src/kraang/

format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

coverage:
	uv run coverage run -m pytest tests/ -v
	uv run coverage report -m
	uv run coverage html

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .mypy_cache .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

publish:
	./scripts/publish.sh $(VERSION)
