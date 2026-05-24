#!/bin/sh
set -eu
cd /app || exit 1

if [ -n "${API_SSL_CERTFILE:-}" ] && [ -n "${API_SSL_KEYFILE:-}" ] \
  && [ -f "$API_SSL_CERTFILE" ] && [ -f "$API_SSL_KEYFILE" ]; then
  exec uvicorn src.api.app:create_app \
    --factory \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --ssl-certfile "$API_SSL_CERTFILE" \
    --ssl-keyfile "$API_SSL_KEYFILE" \
    "$@"
else
  exec uvicorn src.api.app:create_app \
    --factory \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    "$@"
fi
