"""Prompts used by the VisionExtractor.

Kept in English regardless of document language: instructions are for the
model, not for the end user. The transcription itself preserves whatever
language is on the page.
"""

from __future__ import annotations

EXTRACT_TEXT_PROMPT = (
    "You are an expert OCR engine. Transcribe ALL visible text from this "
    "document image with the highest possible fidelity.\n\n"
    "Rules:\n"
    "- Preserve the original reading order (top to bottom, left to right).\n"
    "- Keep headings, bullet lists and paragraph breaks.\n"
    "- Render any tables you see as GitHub-flavored markdown tables.\n"
    "- Do NOT translate. Do NOT summarize. Do NOT add commentary.\n"
    "- If a region is unreadable, write [unreadable] in its place.\n"
    "- Output the transcription only, with no preamble or trailing notes."
)


EXTRACT_KV_PROMPT = (
    "You are an expert document analyst. Identify the key-value pairs in "
    "this document and return STRICT JSON. The transcription provided as "
    "context is authoritative for spelling.\n\n"
    "Return EXACTLY this JSON shape (no extra keys at the top level):\n"
    "{\n"
    '  "document_type": string|null,\n'
    '  "issuer": string|null,\n'
    '  "issued_at": string|null,\n'
    '  "total_amount": string|null,\n'
    '  "currency": string|null,\n'
    '  "parties": [string, ...],\n'
    '  "extras": { "<custom_key>": "<value>", ... }\n'
    "}\n\n"
    "Rules:\n"
    "- Use null when the field is not present. Do NOT invent values.\n"
    "- 'issued_at' MUST be ISO 8601 (YYYY-MM-DD) when a date is found.\n"
    "- 'total_amount' MUST be a numeric string without thousands separators.\n"
    "- 'parties' lists every named party (organizations or persons).\n"
    "- Put any other useful fields under 'extras' as flat string values.\n"
    "- Output ONLY the JSON object. No markdown fences, no commentary."
)


FIX_JSON_PROMPT = (
    "The previous response was not valid JSON. Re-emit the SAME information "
    "as a strict JSON object matching the required shape. Output ONLY the "
    "JSON object, no markdown fences. Previous response:\n\n"
)
