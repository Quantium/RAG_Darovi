.PHONY: up down test lint format install clean typecheck

install:
	pip install -r requirements-dev.txt

up:
	docker compose up -d

down:
	docker compose down

test:
	pytest -v --tb=short

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy --strict src/

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
