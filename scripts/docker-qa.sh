#!/bin/sh
set -eu
ruff check src/ tests/
ruff format --check src/ tests/
mypy --strict src/
pytest -v --tb=short -m "not integration"
