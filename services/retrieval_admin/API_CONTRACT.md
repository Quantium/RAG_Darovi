# Retrieval/Admin <-> Chatbot Contract

This document defines the HTTP contract between:

- `services/retrieval_admin` (provider)
- `services/chatbot_response` (consumer)

No shared Python package is allowed. Integration must be HTTP-only.

## Endpoint

- Method: `POST`
- Path: `/retrieve`
- Auth: optional `X-API-Key` passthrough when configured

## Request body

```json
{
  "query": "What is the invoice total?",
  "top_k": 10,
  "document_type": "pdf"
}
```

Fields:

- `query` (string, required, min length 1)
- `top_k` (integer, optional, default 10)
- `document_type` (string, optional)

## Success response (200)

```json
{
  "query": "What is the invoice total?",
  "context": "[Source: invoice.pdf | Section: page-1]\n...",
  "sources": [
    {
      "source_file_id": "drive-file-id",
      "source_name": "invoice.pdf",
      "section_title": "page-1",
      "chunk_index": 0,
      "text_preview": "Invoice #123 ...",
      "score": 0.91
    }
  ]
}
```

Fields:

- `query` (string)
- `context` (string)
- `sources` (array of source objects)

## Error semantics

- `400`: invalid payload
- `401`: API key invalid/missing when required
- `500`: retrieval backend failure

## Integration notes

- `chatbot_response` forwards `X-API-Key` to `retrieval_admin`.
- `conversation_id` is not required for `/retrieve`; memory is handled by `chatbot_response`.
