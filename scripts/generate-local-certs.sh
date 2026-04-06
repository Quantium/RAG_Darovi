#!/usr/bin/env bash
# Generate a self-signed TLS certificate for local HTTPS (dev / LAN).
# Browsers will show a warning unless you trust the cert (e.g. mkcert) or import cert.pem.
#
# Usage:
#   ./scripts/generate-local-certs.sh [output_dir]
# Env:
#   TLS_SAN_HOSTS  comma-separated hostnames and IPs (default: localhost,envidia,127.0.0.1)

set -euo pipefail

OUT_DIR="${1:-./certs}"
mkdir -p "$OUT_DIR"
CERT="${OUT_DIR}/cert.pem"
KEY="${OUT_DIR}/key.pem"
HOSTS="${TLS_SAN_HOSTS:-localhost,envidia,127.0.0.1}"

TMP_CNF="$(mktemp)"
trap 'rm -f "$TMP_CNF"' EXIT

{
  echo "[req]"
  echo "default_bits = 4096"
  echo "prompt = no"
  echo "default_md = sha256"
  echo "distinguished_name = dn"
  echo "req_extensions = v3_req"
  echo "[dn]"
  echo "CN = localhost"
  echo "[v3_req]"
  echo "subjectAltName = @alt_names"
  echo "[alt_names]"
} >"$TMP_CNF"

i=1
IFS=',' read -r -a PARTS <<<"$HOSTS"
for raw in "${PARTS[@]}"; do
  h=$(echo "$raw" | tr -d '[:space:]')
  [ -z "$h" ] && continue
  if [[ "$h" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "IP.$i = $h" >>"$TMP_CNF"
  else
    echo "DNS.$i = $h" >>"$TMP_CNF"
  fi
  i=$((i + 1))
done

openssl req -x509 -newkey rsa:4096 \
  -keyout "$KEY" \
  -out "$CERT" \
  -days 825 \
  -nodes \
  -config "$TMP_CNF" \
  -extensions v3_req

chmod 600 "$KEY"
echo "Wrote $CERT and $KEY"
echo "Point API_SSL_CERTFILE / API_SSL_KEYFILE at these files (see .env.example)."
