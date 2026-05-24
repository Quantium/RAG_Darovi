PYTHON ?= python3

.PHONY: install test lint format typecheck smoke

install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

test:
	.venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check src tests

format:
	.venv/bin/ruff format src tests

typecheck:
	.venv/bin/mypy --strict src

smoke:
	.venv/bin/python -m pytest -q -m "not integration"
