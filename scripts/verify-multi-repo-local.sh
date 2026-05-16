#!/usr/bin/env bash
set -euo pipefail

echo "[1/5] Sync submodules"
git submodule sync --recursive
git submodule update --init --recursive

echo "[2/5] Run legacy core gate"
make qa-legacy

echo "[3/5] Run service test gates"
make qa-services

echo "[4/5] Run cross-service gates (requires stack up)"
make qa-cross

echo "[5/5] Smoke checks (services must be running)"
curl -fsS "http://localhost:8010/health" >/dev/null
curl -fsS "http://localhost:8020/health" >/dev/null

echo "All local multi-repo verification gates passed."
