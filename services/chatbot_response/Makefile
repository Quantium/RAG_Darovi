PYTHON ?= python3

.PHONY: install test smoke up down

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	pytest -q

smoke:
	pytest -q tests/test_smoke.py

up:
	docker compose -f docker-compose.dev.yml up -d redis ollama

down:
	docker compose -f docker-compose.dev.yml down -v
