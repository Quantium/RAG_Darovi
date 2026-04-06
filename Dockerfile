# --- Stage 1: Install Python dependencies ---
FROM python:3.11-slim AS builder

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Production image ---
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

COPY docker-entrypoint-api.sh docker-healthcheck-api.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint-api.sh /usr/local/bin/docker-healthcheck-api.sh

EXPOSE 8000

CMD ["/usr/local/bin/docker-entrypoint-api.sh"]
