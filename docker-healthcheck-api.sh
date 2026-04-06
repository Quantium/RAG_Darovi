#!/bin/sh
# Self-signed certs require -k; HTTP must not use -k.
set -eu
port="${API_PORT:-8000}"
if [ -n "${API_SSL_CERTFILE:-}" ] && [ -f "${API_SSL_CERTFILE}" ]; then
  curl -fsSk "https://127.0.0.1:${port}/status" >/dev/null
else
  curl -fsS "http://127.0.0.1:${port}/status" >/dev/null
fi
