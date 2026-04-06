.PHONY: up down test lint format install clean typecheck docker-build docker-qa tls-certs

install:
	pip install -r requirements-dev.txt

up:
	docker compose up -d

docker-build:
	docker compose build

docker-qa:
	docker compose --profile qa build app-qa
	docker compose --profile qa run --rm app-qa

tls-certs:
	./scripts/generate-local-certs.sh ./certs

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
