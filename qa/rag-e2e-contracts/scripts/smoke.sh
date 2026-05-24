#!/usr/bin/env bash
set -euo pipefail

: "${RETRIEVAL_ADMIN_BASE_URL:=http://localhost:8010}"
: "${CHATBOT_RESPONSE_BASE_URL:=http://localhost:8020}"

curl -fsS "${RETRIEVAL_ADMIN_BASE_URL}/health" >/dev/null
curl -fsS "${CHATBOT_RESPONSE_BASE_URL}/health" >/dev/null

echo "smoke: retrieval_admin and chatbot_response are healthy"
