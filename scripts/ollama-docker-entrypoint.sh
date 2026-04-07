#!/bin/sh
# Starts Ollama, waits for the API, pulls configured models, then keeps serving.
# Models: OLLAMA_PULL_MODELS (comma-separated) or EMBED_MODEL + LLM_MODEL from .env.
set -eu

READY_FLAG="/tmp/ollama-models-ready"
rm -f "$READY_FLAG"

ollama serve &
OLLAMA_PID=$!

echo "Waiting for Ollama daemon..."
i=0
while ! ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 180 ]; then
    echo "ollama serve did not become ready in time" >&2
    exit 1
  fi
  sleep 1
done

if [ -n "${OLLAMA_PULL_MODELS:-}" ]; then
  RAW="$OLLAMA_PULL_MODELS"
else
  RAW="${EMBED_MODEL:-nomic-embed-text},${LLM_MODEL:-llama3}"
fi

echo "Pulling models: $RAW"
OLDIFS=$IFS
IFS=,
for m in $RAW; do
  m=$(echo "$m" | tr -d ' ')
  if [ -z "$m" ]; then
    continue
  fi
  echo ">>> ollama pull $m"
  ollama pull "$m"
done
IFS=$OLDIFS

touch "$READY_FLAG"
echo "Ollama models ready."

wait "$OLLAMA_PID"
