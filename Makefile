.PHONY: up down clean docker-build docker-qa tls-certs submodules qa-legacy qa-services qa-cross qa-all

up:
	docker compose up -d

submodules:
	git submodule sync --recursive
	git submodule update --init --recursive

docker-build:
	docker compose build

docker-qa:
	docker compose --profile qa build app-qa
	docker compose --profile qa run --rm app-qa

tls-certs:
	./scripts/generate-local-certs.sh ./certs

down:
	docker compose down

qa-legacy:
	cd legacy/rag-legacy-core && make install && make test

qa-services:
	cd services/ingest_raw && make install && make test
	cd services/extract_text && make install && make test
	cd services/retrieval_admin && make install && make test
	cd services/chatbot_response && make install && make test

qa-cross:
	cd qa/rag-e2e-contracts && make install && make test

qa-all: qa-legacy qa-services qa-cross

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
