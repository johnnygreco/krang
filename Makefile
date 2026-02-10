.PHONY: install test lint format coverage clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/
	mypy src/krang/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

coverage:
	coverage run -m pytest tests/ -v
	coverage report -m
	coverage html

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .mypy_cache .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
