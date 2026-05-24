PYTHON ?= python3
ALEMBIC ?= .venv/bin/alembic

.PHONY: install db-upgrade db-downgrade db-current

install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

db-upgrade:
	$(ALEMBIC) upgrade head

db-downgrade:
	$(ALEMBIC) downgrade -1

db-current:
	$(ALEMBIC) current
