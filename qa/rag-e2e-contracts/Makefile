PYTHON ?= python3

.PHONY: install test smoke e2e-install e2e-test

install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

test:
	.venv/bin/python -m pytest -q

smoke:
	./scripts/smoke.sh

e2e-install:
	cd e2e && npm ci && npx playwright install chromium

e2e-test:
	cd e2e && npm run test:e2e
